"""
Management Command: resplit_bundled_pdfs
==========================================
Teilt mehrseitige Sammel-PDFs (Lohnscheine etc.) nachträglich auf.
Jede Seite wird einzeln gescannt und pro Mitarbeiter ein Dokument erstellt.
"""

from django.core.management.base import BaseCommand
from dms.models import Document
from dms.encryption import decrypt_data, encrypt_data
from dms.tasks import (
    find_employee_by_id, 
    parse_employee_id_from_datamatrix, 
    parse_datamatrix_metadata,
    classify_sage_document,
    auto_classify_document
)
from pathlib import Path
import hashlib


class Command(BaseCommand):
    help = 'Teilt mehrseitige Sammel-PDFs nachträglich auf'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Zeigt Änderungen ohne sie auszuführen',
        )
        parser.add_argument(
            '--timeout',
            type=int,
            default=8,
            help='Timeout pro Seite in Sekunden (default: 8)',
        )
        parser.add_argument(
            '--doc-id',
            type=str,
            help='Nur ein bestimmtes Dokument verarbeiten (UUID)',
        )
        parser.add_argument(
            '--group-pages',
            action='store_true',
            help='Gruppiert Seiten pro Mitarbeiter (Standard: jede Seite = 1 Dokument)',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        timeout = options.get('timeout', 8)
        doc_id = options.get('doc_id')
        group_pages = options.get('group_pages', False)
        
        if dry_run:
            self.stdout.write(self.style.WARNING('=== DRY RUN ===\n'))
        
        if group_pages:
            self.stdout.write(self.style.WARNING('Modus: Gruppierung nach Mitarbeiter\n'))
        else:
            self.stdout.write('Modus: Eine Seite = Ein Dokument\n')
        
        if doc_id:
            docs = Document.objects.filter(id=doc_id)
        else:
            docs = Document.objects.filter(
                status='REVIEW_NEEDED',
                employee__isnull=True,
                file_extension='.pdf'
            ).select_related('tenant')
        
        total = docs.count()
        self.stdout.write(f"Gefunden: {total} Dokumente zum Prüfen\n")
        
        split_count = 0
        skipped = 0
        
        for doc in docs:
            one_page_per_doc = not group_pages
            result = self._process_document(doc, timeout, dry_run, one_page_per_doc)
            if result > 0:
                split_count += result
            else:
                skipped += 1
        
        self.stdout.write(self.style.SUCCESS(
            f"\nErgebnis: {split_count} neue Dokumente erstellt, {skipped} übersprungen"
        ))
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\n=== DRY RUN - Keine Änderungen gespeichert ==='))
    
    def _process_document(self, doc, timeout_per_page, dry_run, one_page_per_doc=False):
        """Verarbeitet ein Dokument und teilt es auf wenn nötig"""
        import fitz
        
        self.stdout.write(f"\nVerarbeite: {doc.original_filename}")
        
        try:
            pdf_bytes = decrypt_data(doc.encrypted_content)
            pdf_doc = fitz.open(stream=pdf_bytes, filetype='pdf')
            page_count = len(pdf_doc)
            
            self.stdout.write(f"  Seiten: {page_count}")
            
            if page_count <= 1:
                pdf_doc.close()
                self.stdout.write("  -> Übersprungen (nur 1 Seite)")
                return 0
            
            if one_page_per_doc:
                return self._process_one_page_per_doc(doc, pdf_doc, pdf_bytes, timeout_per_page, dry_run)
            
            segments = []
            current_segment = {'employee_id': None, 'mandant_code': None, 'pages': []}
            
            for page_num in range(page_count):
                page_emp_id = None
                page_mandant = None
                
                try:
                    result = self._scan_page_with_timeout(pdf_doc, page_num, timeout_per_page)
                    if result:
                        page_emp_id = result.get('employee_id')
                        page_mandant = result.get('mandant_code')
                        self.stdout.write(f"    Seite {page_num+1}: MA={page_emp_id}, MD={page_mandant}")
                    else:
                        self.stdout.write(f"    Seite {page_num+1}: kein DataMatrix")
                except TimeoutError:
                    self.stdout.write(self.style.WARNING(f"    Seite {page_num+1}: Timeout"))
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"    Seite {page_num+1}: Fehler {e}"))
                
                if page_emp_id and page_emp_id != current_segment['employee_id']:
                    if current_segment['pages']:
                        segments.append(current_segment)
                    current_segment = {
                        'employee_id': page_emp_id, 
                        'mandant_code': page_mandant,
                        'pages': [page_num]
                    }
                else:
                    current_segment['pages'].append(page_num)
                    if page_emp_id:
                        current_segment['employee_id'] = page_emp_id
                    if page_mandant and not current_segment['mandant_code']:
                        current_segment['mandant_code'] = page_mandant
            
            if current_segment['pages']:
                segments.append(current_segment)
            
            segments_with_emp = [s for s in segments if s['employee_id']]
            
            if len(segments_with_emp) <= 1:
                pdf_doc.close()
                self.stdout.write("  -> Übersprungen (nur ein Mitarbeiter)")
                return 0
            
            self.stdout.write(f"  Gefunden: {len(segments_with_emp)} Mitarbeiter-Segmente")
            
            if dry_run:
                pdf_doc.close()
                return len(segments_with_emp)
            
            created_docs = []
            base_name = Path(doc.original_filename).stem
            
            for segment in segments:
                emp_id = segment['employee_id']
                mandant_code = segment['mandant_code']
                pages = segment['pages']
                
                if not emp_id:
                    continue
                
                new_pdf = fitz.open()
                for page_num in pages:
                    new_pdf.insert_pdf(pdf_doc, from_page=page_num, to_page=page_num)
                
                pdf_content = new_pdf.tobytes()
                new_pdf.close()
                
                encrypted_content = encrypt_data(pdf_content)
                file_hash = hashlib.sha256(pdf_content).hexdigest()
                
                employee = find_employee_by_id(emp_id, tenant=doc.tenant, mandant_code=mandant_code)
                status = 'ASSIGNED' if employee else 'REVIEW_NEEDED'
                
                new_filename = f"{base_name}_MA{emp_id}.pdf"
                
                doc_type, _, category, description = classify_sage_document(doc.original_filename)
                
                new_metadata = dict(doc.metadata)
                new_metadata['employee_id_from_datamatrix'] = emp_id
                new_metadata['mandant_code'] = mandant_code
                new_metadata['split_from'] = str(doc.id)
                new_metadata['pages_in_split'] = len(pages)
                
                new_doc = Document.objects.create(
                    tenant=doc.tenant,
                    title=Path(new_filename).stem,
                    original_filename=new_filename,
                    file_extension='.pdf',
                    mime_type='application/pdf',
                    encrypted_content=encrypted_content,
                    file_size=len(pdf_content),
                    employee=employee,
                    status=status,
                    source=doc.source,
                    sha256_hash=file_hash,
                    metadata=new_metadata,
                    period_year=doc.period_year,
                    period_month=doc.period_month
                )
                
                auto_classify_document(new_doc, tenant=doc.tenant)
                created_docs.append(new_doc)
                
                self.stdout.write(
                    f"    Erstellt: {new_filename} ({len(pages)} Seiten) -> "
                    f"{employee.first_name + ' ' + employee.last_name if employee else 'REVIEW'}"
                )
            
            pdf_doc.close()
            
            doc.status = 'ARCHIVED'
            doc.notes = f"Aufgeteilt in {len(created_docs)} Einzeldokumente"
            doc.save(update_fields=['status', 'notes'])
            
            return len(created_docs)
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  Fehler: {str(e)}"))
            return 0
    
    def _scan_page_with_timeout(self, pdf_doc, page_num, timeout_seconds):
        """Scannt eine Seite mit Timeout (Thread-basiert für Docker-Kompatibilität)"""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
        from pylibdmtx.pylibdmtx import decode
        from PIL import Image
        import fitz
        import io
        
        def do_scan():
            page = pdf_doc[page_num]
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            
            decoded = decode(img, timeout=timeout_seconds * 1000, max_count=1)
            
            for d in decoded:
                raw_data = d.data.decode('utf-8')
                emp_id = parse_employee_id_from_datamatrix(raw_data)
                if emp_id:
                    metadata = parse_datamatrix_metadata(raw_data)
                    return {
                        'employee_id': emp_id,
                        'mandant_code': metadata.get('tenant_code'),
                        'raw': raw_data
                    }
            return None
        
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(do_scan)
                return future.result(timeout=timeout_seconds + 2)
        except FuturesTimeoutError:
            raise TimeoutError("Scan timeout")
        except Exception as e:
            raise e
    
    def _process_one_page_per_doc(self, doc, pdf_doc, pdf_bytes, timeout_per_page, dry_run):
        """Jede Seite wird ein eigenes Dokument - scannt DataMatrix für MA-Zuweisung"""
        import fitz
        
        page_count = len(pdf_doc)
        created_count = 0
        base_name = Path(doc.original_filename).stem
        
        for page_num in range(page_count):
            emp_id = None
            mandant_code = None
            
            try:
                result = self._scan_page_with_timeout(pdf_doc, page_num, timeout_per_page)
                if result:
                    emp_id = result['employee_id']
                    mandant_code = result.get('mandant_code')
                    self.stdout.write(f"    Seite {page_num + 1}: MA={emp_id}, MD={mandant_code}")
                else:
                    self.stdout.write(f"    Seite {page_num + 1}: kein DataMatrix")
            except TimeoutError:
                self.stdout.write(f"    Seite {page_num + 1}: Timeout")
            except Exception as e:
                self.stdout.write(f"    Seite {page_num + 1}: Fehler: {str(e)}")
            
            if dry_run:
                created_count += 1
                continue
            
            new_pdf = fitz.open()
            new_pdf.insert_pdf(pdf_doc, from_page=page_num, to_page=page_num)
            pdf_content = new_pdf.tobytes()
            new_pdf.close()
            
            encrypted_content = encrypt_data(pdf_content)
            file_hash = hashlib.sha256(pdf_content).hexdigest()
            
            employee = None
            if emp_id:
                employee = find_employee_by_id(emp_id, tenant=doc.tenant, mandant_code=mandant_code)
            
            status = 'ASSIGNED' if employee else 'REVIEW_NEEDED'
            suffix = f"_MA{emp_id}" if emp_id else f"_S{page_num + 1}"
            new_filename = f"{base_name}{suffix}.pdf"
            
            doc_type, _, category, description = classify_sage_document(doc.original_filename)
            
            new_metadata = dict(doc.metadata) if doc.metadata else {}
            if emp_id:
                new_metadata['employee_id_from_datamatrix'] = emp_id
            if mandant_code:
                new_metadata['mandant_code'] = mandant_code
            new_metadata['split_from'] = str(doc.id)
            new_metadata['page_number'] = page_num + 1
            
            new_doc = Document.objects.create(
                tenant=doc.tenant,
                title=Path(new_filename).stem,
                original_filename=new_filename,
                file_extension='.pdf',
                mime_type='application/pdf',
                encrypted_content=encrypted_content,
                file_size=len(pdf_content),
                employee=employee,
                status=status,
                source=doc.source,
                sha256_hash=file_hash,
                metadata=new_metadata,
                period_year=doc.period_year,
                period_month=doc.period_month
            )
            
            auto_classify_document(new_doc, tenant=doc.tenant)
            created_count += 1
            
            emp_name = f"{employee.first_name} {employee.last_name}" if employee else "REVIEW"
            self.stdout.write(f"    -> Erstellt: {new_filename} -> {emp_name}")
        
        if not dry_run:
            pdf_doc.close()
            doc.status = 'ARCHIVED'
            doc.notes = f"Aufgeteilt in {created_count} Einzeldokumente (1 pro Seite)"
            doc.save(update_fields=['status', 'notes'])
        
        self.stdout.write(f"  Gesamt: {created_count} Dokumente")
        return created_count
