import tempfile
from pathlib import Path
from django.core.management.base import BaseCommand
from dms.models import Document, ProcessedFile, Tenant
from dms.tasks import (
    split_pdf_by_datamatrix, 
    find_employee_by_id, 
    classify_sage_document,
    auto_classify_document,
    log_system_event,
    parse_month_folder
)
from dms.encryption import encrypt_data, decrypt_data, calculate_sha256_chunked


class Command(BaseCommand):
    help = 'Teilt bestehende Sammel-PDFs mit DataMatrix-Codes nachträglich auf'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Zeigt nur an was geändert würde, ohne zu speichern',
        )
        parser.add_argument(
            '--tenant',
            type=str,
            help='Nur bestimmten Mandanten verarbeiten (Tenant-Code)',
        )
        parser.add_argument(
            '--document-id',
            type=str,
            help='Nur ein bestimmtes Dokument verarbeiten (UUID)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        tenant_code = options.get('tenant')
        document_id = options.get('document_id')
        
        docs = Document.objects.filter(
            mime_type='application/pdf',
            source='SAGE',
        )
        
        if tenant_code:
            try:
                tenant = Tenant.objects.get(code=tenant_code)
                docs = docs.filter(tenant=tenant)
            except Tenant.DoesNotExist:
                self.stderr.write(f"Mandant {tenant_code} nicht gefunden")
                return
        
        if document_id:
            docs = docs.filter(id=document_id)
        
        total = docs.count()
        processed = 0
        split_count = 0
        deleted_count = 0
        
        self.stdout.write(f"Prüfe {total} PDF-Dokumente auf Split-Möglichkeit...")
        
        for doc in docs.iterator():
            metadata = doc.metadata or {}
            
            if metadata.get('split_from'):
                continue
            
            try:
                decrypted_content = decrypt_data(doc.encrypted_content)
            except Exception as e:
                self.stderr.write(f"  Entschlüsselung fehlgeschlagen: {doc.original_filename} - {e}")
                continue
            
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_pdf_path = Path(temp_dir) / doc.original_filename
                with open(temp_pdf_path, 'wb') as f:
                    f.write(decrypted_content)
                
                split_output_dir = Path(temp_dir) / 'split_output'
                split_results = split_pdf_by_datamatrix(str(temp_pdf_path), str(split_output_dir))
                
                if not split_results or len(split_results) <= 1:
                    continue
                
                processed += 1
                
                if dry_run:
                    self.stdout.write(self.style.WARNING(
                        f"  [DRY-RUN] Würde teilen: {doc.original_filename} → {len(split_results)} Dokumente"
                    ))
                    for sr in split_results:
                        emp_id = sr.get('employee_id', 'UNBEKANNT')
                        pages = sr.get('page_count', 0)
                        self.stdout.write(f"    → MA {emp_id}: {pages} Seiten")
                    continue
                
                self.stdout.write(f"  Teile: {doc.original_filename} → {len(split_results)} Dokumente")
                
                month_folder = metadata.get('month_folder')
                tenant = doc.tenant
                
                for split_info in split_results:
                    split_path = Path(split_info['file_path'])
                    emp_id = split_info['employee_id']
                    
                    with open(split_path, 'rb') as sf:
                        split_content = sf.read()
                    split_encrypted = encrypt_data(split_content)
                    split_hash = calculate_sha256_chunked(str(split_path))
                    split_size = len(split_content)
                    
                    split_employee = find_employee_by_id(emp_id, tenant=tenant)
                    split_status = 'ASSIGNED' if split_employee else 'REVIEW_NEEDED'
                    
                    doc_type_split, _, category_split, desc_split = classify_sage_document(doc.original_filename)
                    
                    split_metadata = {
                        'original_path': metadata.get('original_path', ''),
                        'split_from': doc.original_filename,
                        'employee_id_from_datamatrix': emp_id,
                        'pages_in_split': split_info['page_count'],
                        'tenant_code': tenant.code if tenant else None,
                        'doc_type': doc_type_split,
                        'is_personnel_document': True,
                        'month_folder': month_folder,
                        'resplit_from_document_id': str(doc.id),
                    }
                    
                    period_year, period_month = parse_month_folder(month_folder)
                    split_doc = Document.objects.create(
                        tenant=tenant,
                        title=split_path.stem,
                        original_filename=split_path.name,
                        file_extension='.pdf',
                        mime_type='application/pdf',
                        encrypted_content=split_encrypted,
                        file_size=split_size,
                        employee=split_employee,
                        status=split_status,
                        source='SAGE',
                        sha256_hash=split_hash,
                        metadata=split_metadata,
                        period_year=period_year,
                        period_month=period_month
                    )
                    
                    auto_classify_document(split_doc, tenant=tenant)
                    split_count += 1
                    
                    emp_name = split_employee.full_name if split_employee else f"MA {emp_id}"
                    self.stdout.write(f"    → Erstellt: {split_path.name} für {emp_name}")
                
                doc.delete()
                deleted_count += 1
                
                log_system_event('INFO', 'Resplit', 
                    f"Dokument nachträglich geteilt: {doc.original_filename} → {len(split_results)} Einzeldokumente",
                    {'original_id': str(doc.id), 'split_count': len(split_results)})
        
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"\n[DRY-RUN] Würde {processed} Dokumente teilen → {split_count} neue Dokumente"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\n{processed} Sammel-PDFs geteilt → {split_count} neue Dokumente erstellt, {deleted_count} Originale gelöscht"
            ))
