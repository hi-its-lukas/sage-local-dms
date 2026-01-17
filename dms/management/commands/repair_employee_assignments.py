"""
Management Command: repair_employee_assignments
=================================================
Repariert Dokumente mit Status REVIEW_NEEDED durch erneute Mitarbeiter-Zuordnung.
Scannt DataMatrix erneut aus verschlüsseltem Inhalt wenn nötig.
"""

from django.core.management.base import BaseCommand
from dms.models import Document, Employee
import signal


class Command(BaseCommand):
    help = 'Repariert REVIEW_NEEDED Dokumente durch erneute Mitarbeiter-Zuordnung'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Zeigt Änderungen ohne sie auszuführen',
        )
        parser.add_argument(
            '--rescan',
            action='store_true',
            help='DataMatrix erneut aus PDF scannen',
        )
        parser.add_argument(
            '--timeout',
            type=int,
            default=5,
            help='Timeout pro Seite in Sekunden (default: 5)',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        rescan = options.get('rescan', False)
        timeout = options.get('timeout', 5)
        
        if dry_run:
            self.stdout.write(self.style.WARNING('=== DRY RUN ===\n'))
        
        from dms.tasks import find_employee_by_id, parse_employee_id_from_datamatrix, parse_datamatrix_metadata
        from dms.encryption import decrypt_data
        
        docs = Document.objects.filter(
            status='REVIEW_NEEDED',
            employee__isnull=True
        ).select_related('tenant')
        
        total = docs.count()
        self.stdout.write(f"Gefunden: {total} Dokumente mit REVIEW_NEEDED und ohne Mitarbeiter\n")
        
        fixed = 0
        failed = 0
        skipped = 0
        
        for doc in docs:
            emp_id = doc.metadata.get('employee_id_from_datamatrix')
            mandant_code = doc.metadata.get('mandant_code')
            
            if not emp_id and rescan and doc.file_extension.lower() == '.pdf':
                self.stdout.write(f"  Scanne: {doc.original_filename[:50]}...")
                scan_result = self._scan_datamatrix_from_doc(doc, timeout)
                if scan_result:
                    emp_id = scan_result.get('employee_id')
                    mandant_code = scan_result.get('mandant_code')
                    self.stdout.write(f"    -> Gefunden: MA={emp_id}, MD={mandant_code}")
            
            if not emp_id:
                skipped += 1
                continue
            
            employee = find_employee_by_id(
                emp_id, 
                tenant=doc.tenant, 
                mandant_code=mandant_code
            )
            
            if employee:
                self.stdout.write(
                    f"  {doc.original_filename[:40]}: MA-ID {emp_id} -> "
                    f"{employee.first_name} {employee.last_name} ({employee.employee_id})"
                )
                
                if not dry_run:
                    doc.employee = employee
                    doc.status = 'ASSIGNED'
                    
                    if emp_id and 'employee_id_from_datamatrix' not in doc.metadata:
                        doc.metadata['employee_id_from_datamatrix'] = emp_id
                    if mandant_code and 'mandant_code' not in doc.metadata:
                        doc.metadata['mandant_code'] = mandant_code
                    
                    doc.save(update_fields=['employee', 'status', 'metadata'])
                    
                    if hasattr(employee, 'personnel_file') and employee.personnel_file:
                        from dms.models import PersonnelFileEntry
                        if doc.document_type and doc.document_type.file_category:
                            PersonnelFileEntry.objects.get_or_create(
                                personnel_file=employee.personnel_file,
                                document=doc,
                                defaults={
                                    'category': doc.document_type.file_category,
                                    'notes': f'Auto-Reparatur: {doc.document_type.name}'
                                }
                            )
                
                fixed += 1
            else:
                self.stdout.write(
                    self.style.WARNING(f"  {doc.original_filename[:40]}: MA-ID {emp_id} nicht gefunden")
                )
                failed += 1
        
        self.stdout.write(self.style.SUCCESS(
            f"\nErgebnis: {fixed} repariert, {failed} nicht zuordenbar, {skipped} übersprungen"
        ))
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\n=== DRY RUN - Keine Änderungen gespeichert ==='))
    
    def _scan_datamatrix_from_doc(self, doc, timeout_per_page=5):
        """Scannt DataMatrix aus dem verschlüsselten PDF-Inhalt"""
        from dms.encryption import decrypt_data
        from dms.tasks import parse_employee_id_from_datamatrix, parse_datamatrix_metadata
        
        def timeout_handler(signum, frame):
            raise TimeoutError("Scan timeout")
        
        try:
            import fitz
            from pylibdmtx.pylibdmtx import decode
            from PIL import Image
            import io
            
            pdf_bytes = decrypt_data(doc.encrypted_content)
            pdf_doc = fitz.open(stream=pdf_bytes, filetype='pdf')
            
            for page_num in range(min(len(pdf_doc), 3)):
                try:
                    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(timeout_per_page)
                    
                    try:
                        page = pdf_doc[page_num]
                        pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2))
                        img_data = pix.tobytes("png")
                        img = Image.open(io.BytesIO(img_data))
                        
                        decoded = decode(img)
                        
                        for d in decoded:
                            raw_data = d.data.decode('utf-8')
                            emp_id = parse_employee_id_from_datamatrix(raw_data)
                            if emp_id:
                                metadata = parse_datamatrix_metadata(raw_data)
                                pdf_doc.close()
                                return {
                                    'employee_id': emp_id,
                                    'mandant_code': metadata.get('tenant_code'),
                                    'raw': raw_data
                                }
                    finally:
                        signal.alarm(0)
                        signal.signal(signal.SIGALRM, old_handler)
                        
                except TimeoutError:
                    self.stdout.write(self.style.WARNING(f"    Timeout auf Seite {page_num+1}"))
                    continue
                except Exception as e:
                    continue
            
            pdf_doc.close()
            return None
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"    Fehler: {str(e)}"))
            return None
