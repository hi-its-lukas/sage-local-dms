import os
import logging
import magic
from pathlib import Path
from datetime import datetime

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import Document, ProcessedFile, Employee, Task, EmailConfig, SystemLog, Tenant
from .encryption import encrypt_data, decrypt_data, calculate_sha256, encrypt_file
import re

logger = logging.getLogger('dms')


def log_system_event(level, source, message, details=None):
    SystemLog.objects.create(
        level=level,
        source=source,
        message=message,
        details=details or {}
    )
    getattr(logger, level.lower())(f"[{source}] {message}")


def get_mime_type(file_path):
    try:
        return magic.from_file(file_path, mime=True)
    except Exception:
        return 'application/octet-stream'


def extract_employee_from_datamatrix(file_path):
    try:
        import fitz
        from pylibdmtx.pylibdmtx import decode
        from PIL import Image
        import io
        
        doc = fitz.open(file_path)
        employee_ids = []
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            
            decoded = decode(img)
            for d in decoded:
                data = d.data.decode('utf-8')
                employee_ids.append({'page': page_num, 'data': data})
        
        doc.close()
        return employee_ids
    except Exception as e:
        logger.warning(f"DataMatrix extraction failed for {file_path}: {e}")
        return None


def find_employee_by_id(employee_id, tenant=None):
    try:
        queryset = Employee.objects.all()
        if tenant:
            queryset = queryset.filter(tenant=tenant)
        return queryset.get(employee_id=employee_id)
    except Employee.DoesNotExist:
        return None


@shared_task(bind=True, max_retries=3)
def scan_sage_archive(self):
    sage_path = Path(settings.SAGE_ARCHIVE_PATH)
    
    if not sage_path.exists():
        log_system_event('WARNING', 'SageScanner', f"Sage archive path does not exist: {sage_path}")
        return {'status': 'error', 'message': 'Path does not exist'}
    
    processed_count = 0
    skipped_count = 0
    error_count = 0
    tenant_count = 0
    
    supported_extensions = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.jpg', '.jpeg', '.png', '.tiff', '.txt'}
    tenant_folder_pattern = re.compile(r'^\d{8}$')
    
    try:
        for tenant_folder in sage_path.iterdir():
            if not tenant_folder.is_dir():
                continue
            
            if not tenant_folder_pattern.match(tenant_folder.name):
                continue
            
            tenant_code = tenant_folder.name
            tenant, created = Tenant.objects.get_or_create(
                code=tenant_code,
                defaults={'name': f'Mandant {tenant_code}', 'is_active': True}
            )
            
            if created:
                log_system_event('INFO', 'SageScanner', f"Neuer Mandant erstellt: {tenant_code}")
                tenant_count += 1
            
            for file_path in tenant_folder.rglob('*'):
                if not file_path.is_file():
                    continue
                
                if file_path.suffix.lower() not in supported_extensions:
                    continue
                
                try:
                    with open(file_path, 'rb') as f:
                        content = f.read()
                    
                    file_hash = calculate_sha256(content)
                    
                    if ProcessedFile.objects.filter(tenant=tenant, sha256_hash=file_hash).exists():
                        skipped_count += 1
                        continue
                    
                    encrypted_content = encrypt_data(content)
                    mime_type = get_mime_type(str(file_path))
                    
                    employee = None
                    status = 'UNASSIGNED'
                    needs_review = False
                    
                    if file_path.suffix.lower() == '.pdf':
                        dm_data = extract_employee_from_datamatrix(str(file_path))
                        if dm_data is None:
                            needs_review = True
                            status = 'REVIEW_NEEDED'
                        elif dm_data:
                            first_emp_data = dm_data[0].get('data', '')
                            employee = find_employee_by_id(first_emp_data, tenant=tenant)
                            if employee:
                                status = 'ASSIGNED'
                            else:
                                status = 'UNASSIGNED'
                    
                    document = Document.objects.create(
                        tenant=tenant,
                        title=file_path.stem,
                        original_filename=file_path.name,
                        file_extension=file_path.suffix,
                        mime_type=mime_type,
                        encrypted_content=encrypted_content,
                        file_size=len(content),
                        employee=employee,
                        status=status,
                        source='SAGE',
                        sha256_hash=file_hash,
                        metadata={
                            'original_path': str(file_path),
                            'needs_review': needs_review,
                            'tenant_code': tenant_code
                        }
                    )
                    
                    ProcessedFile.objects.create(
                        tenant=tenant,
                        sha256_hash=file_hash,
                        original_path=str(file_path),
                        document=document
                    )
                    
                    processed_count += 1
                    
                    if needs_review:
                        log_system_event('WARNING', 'SageScanner', 
                            f"File requires review (DataMatrix issue): {file_path.name}",
                            {'document_id': str(document.id), 'tenant': tenant_code})
                    
                except Exception as e:
                    error_count += 1
                    log_system_event('ERROR', 'SageScanner', 
                        f"Failed to process file: {file_path.name}",
                        {'error': str(e), 'tenant': tenant_code})
        
        log_system_event('INFO', 'SageScanner', 
            f"Scan complete: {processed_count} processed, {skipped_count} skipped, {error_count} errors, {tenant_count} new tenants")
        
        return {
            'status': 'success',
            'processed': processed_count,
            'skipped': skipped_count,
            'errors': error_count,
            'new_tenants': tenant_count
        }
        
    except Exception as e:
        log_system_event('CRITICAL', 'SageScanner', f"Sage scan failed: {str(e)}")
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def scan_manual_input(self):
    manual_path = Path(settings.MANUAL_INPUT_PATH)
    processed_path = manual_path / 'processed'
    
    if not manual_path.exists():
        log_system_event('WARNING', 'ManualScanner', f"Manual input path does not exist: {manual_path}")
        return {'status': 'error', 'message': 'Path does not exist'}
    
    processed_path.mkdir(exist_ok=True)
    
    processed_count = 0
    error_count = 0
    
    supported_extensions = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.jpg', '.jpeg', '.png', '.tiff', '.txt'}
    
    try:
        for file_path in manual_path.iterdir():
            if not file_path.is_file():
                continue
            
            if file_path.suffix.lower() not in supported_extensions:
                continue
            
            try:
                with open(file_path, 'rb') as f:
                    content = f.read()
                
                file_hash = calculate_sha256(content)
                
                if ProcessedFile.objects.filter(sha256_hash=file_hash).exists():
                    dest_path = processed_path / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_dup_{file_path.name}"
                    file_path.rename(dest_path)
                    log_system_event('INFO', 'ManualScanner', 
                        f"Skipped duplicate file: {file_path.name}",
                        {'hash': file_hash[:16]})
                    continue
                
                encrypted_content = encrypt_data(content)
                mime_type = get_mime_type(str(file_path))
                
                document = Document.objects.create(
                    title=file_path.stem,
                    original_filename=file_path.name,
                    file_extension=file_path.suffix,
                    mime_type=mime_type,
                    encrypted_content=encrypted_content,
                    file_size=len(content),
                    status='UNASSIGNED',
                    source='MANUAL',
                    sha256_hash=file_hash,
                    metadata={'original_path': str(file_path)}
                )
                
                ProcessedFile.objects.create(
                    sha256_hash=file_hash,
                    original_path=str(file_path),
                    document=document
                )
                
                dest_path = processed_path / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file_path.name}"
                file_path.rename(dest_path)
                
                processed_count += 1
                log_system_event('INFO', 'ManualScanner', 
                    f"Processed file: {file_path.name}",
                    {'document_id': str(document.id)})
                
            except Exception as e:
                error_count += 1
                log_system_event('ERROR', 'ManualScanner', 
                    f"Failed to process file: {file_path.name}",
                    {'error': str(e)})
        
        return {
            'status': 'success',
            'processed': processed_count,
            'errors': error_count
        }
        
    except Exception as e:
        log_system_event('CRITICAL', 'ManualScanner', f"Manual scan failed: {str(e)}")
        raise self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def poll_email_inbox(self):
    from O365 import Account, FileSystemTokenBackend
    
    configs = EmailConfig.objects.filter(is_active=True)
    
    for config in configs:
        try:
            client_secret = decrypt_data(config.encrypted_client_secret).decode('utf-8')
            
            credentials = (config.client_id, client_secret)
            token_backend = FileSystemTokenBackend(
                token_path=Path(settings.BASE_DIR) / 'data',
                token_filename=f'o365_token_{config.id}.txt'
            )
            
            account = Account(
                credentials,
                tenant_id=config.tenant_id,
                token_backend=token_backend
            )
            
            if not account.is_authenticated:
                log_system_event('WARNING', 'EmailPoller', 
                    f"Account not authenticated: {config.name}. Manual auth required.")
                continue
            
            mailbox = account.mailbox(resource=config.target_mailbox)
            folder = mailbox.get_folder(folder_name=config.target_folder)
            
            if config.last_sync:
                query = folder.new_query().on_attribute('receivedDateTime').greater(config.last_sync)
                messages = folder.get_messages(query=query, limit=50)
            else:
                messages = folder.get_messages(limit=50)
            
            for message in messages:
                try:
                    process_email_message(message, config)
                except Exception as e:
                    log_system_event('ERROR', 'EmailPoller', 
                        f"Failed to process email: {message.subject}",
                        {'error': str(e)})
            
            config.last_sync = timezone.now()
            config.save()
            
            log_system_event('INFO', 'EmailPoller', 
                f"Email polling complete for: {config.name}")
            
        except Exception as e:
            log_system_event('ERROR', 'EmailPoller', 
                f"Email polling failed for: {config.name}",
                {'error': str(e)})
    
    return {'status': 'success'}


def process_email_message(message, config):
    import pdfkit
    from email.utils import formataddr
    
    email_archive_path = Path(settings.EMAIL_ARCHIVE_PATH)
    email_archive_path.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    subject_safe = "".join(c for c in message.subject if c.isalnum() or c in (' ', '-', '_'))[:50]
    
    eml_content = f"""From: {message.sender.address}
To: {config.target_mailbox}
Subject: {message.subject}
Date: {message.received}

{message.body or ''}
"""
    
    eml_encrypted = encrypt_data(eml_content.encode('utf-8'))
    eml_hash = calculate_sha256(eml_content.encode('utf-8'))
    
    eml_doc = Document.objects.create(
        title=f"Email: {message.subject}",
        original_filename=f"{timestamp}_{subject_safe}.eml",
        file_extension='.eml',
        mime_type='message/rfc822',
        encrypted_content=eml_encrypted,
        file_size=len(eml_content),
        status='UNASSIGNED',
        source='EMAIL',
        sha256_hash=eml_hash,
        metadata={
            'sender': message.sender.address,
            'received': str(message.received),
            'has_attachments': message.has_attachments
        }
    )
    
    try:
        html_content = f"""
        <html>
        <head><style>body {{ font-family: Arial, sans-serif; }}</style></head>
        <body>
        <h2>{message.subject}</h2>
        <p><strong>From:</strong> {message.sender.address}</p>
        <p><strong>Date:</strong> {message.received}</p>
        <hr>
        {message.body or 'No content'}
        </body>
        </html>
        """
        
        pdf_content = pdfkit.from_string(html_content, False)
        pdf_encrypted = encrypt_data(pdf_content)
        pdf_hash = calculate_sha256(pdf_content)
        
        Document.objects.create(
            title=f"Email PDF: {message.subject}",
            original_filename=f"{timestamp}_{subject_safe}.pdf",
            file_extension='.pdf',
            mime_type='application/pdf',
            encrypted_content=pdf_encrypted,
            file_size=len(pdf_content),
            status='UNASSIGNED',
            source='EMAIL',
            sha256_hash=pdf_hash,
            metadata={'parent_email_id': str(eml_doc.id)}
        )
    except Exception as e:
        log_system_event('WARNING', 'EmailPoller', 
            f"Failed to convert email to PDF: {message.subject}",
            {'error': str(e)})
    
    if message.has_attachments:
        for attachment in message.attachments:
            try:
                att_content = attachment.content
                att_encrypted = encrypt_data(att_content)
                att_hash = calculate_sha256(att_content)
                
                Document.objects.create(
                    title=f"Attachment: {attachment.name}",
                    original_filename=attachment.name,
                    file_extension=Path(attachment.name).suffix,
                    mime_type=attachment.content_type or 'application/octet-stream',
                    encrypted_content=att_encrypted,
                    file_size=len(att_content),
                    status='UNASSIGNED',
                    source='EMAIL',
                    sha256_hash=att_hash,
                    metadata={'parent_email_id': str(eml_doc.id)}
                )
            except Exception as e:
                log_system_event('WARNING', 'EmailPoller', 
                    f"Failed to process attachment: {attachment.name}",
                    {'error': str(e)})
    
    Task.objects.create(
        title=f"Review Email: {message.subject}",
        description=f"New email received from {message.sender.address}",
        document=eml_doc,
        priority=2
    )
    
    log_system_event('INFO', 'EmailPoller', 
        f"Processed email: {message.subject}",
        {'document_id': str(eml_doc.id)})


@shared_task(bind=True, max_retries=3)
def sync_sage_cloud_employees(self):
    """Sync employees from Sage Cloud and create personnel files"""
    from .connectors.sage_cloud import SageCloudConnector
    
    try:
        connector = SageCloudConnector()
        if connector.connect():
            stats = connector.sync_employees()
            log_system_event('INFO', 'SageCloudSync', 
                'Mitarbeiter-Synchronisation abgeschlossen', stats)
            return {'status': 'success', **stats}
        else:
            log_system_event('WARNING', 'SageCloudSync', 
                'Verbindung zu Sage Cloud nicht möglich')
            return {'status': 'connection_failed'}
    except Exception as e:
        log_system_event('ERROR', 'SageCloudSync', 
            f'Sage Cloud Sync fehlgeschlagen: {str(e)}')
        raise self.retry(exc=e, countdown=300)


@shared_task(bind=True, max_retries=3)
def import_sage_cloud_leave_requests(self):
    """Import approved leave requests from Sage Cloud"""
    from .connectors.sage_cloud import SageCloudConnector
    from datetime import timedelta
    
    try:
        connector = SageCloudConnector()
        since_date = (timezone.now() - timedelta(days=30)).date()
        stats = connector.import_leave_requests(since_date)
        log_system_event('INFO', 'SageCloudImport', 
            'Urlaubsanträge-Import abgeschlossen', stats)
        return {'status': 'success', **stats}
    except Exception as e:
        log_system_event('ERROR', 'SageCloudImport', 
            f'Urlaubsanträge-Import fehlgeschlagen: {str(e)}')
        raise self.retry(exc=e, countdown=300)


@shared_task(bind=True, max_retries=3)
def import_sage_cloud_timesheets(self, year: int = None, month: int = None):
    """Import monthly timesheets from Sage Cloud"""
    from .connectors.sage_cloud import SageCloudConnector
    
    if year is None or month is None:
        now = timezone.now()
        if now.month == 1:
            year = now.year - 1
            month = 12
        else:
            year = now.year
            month = now.month - 1
    
    try:
        connector = SageCloudConnector()
        stats = connector.import_timesheets(year, month)
        log_system_event('INFO', 'SageCloudImport', 
            f'Zeiterfassungs-Import für {month:02d}/{year} abgeschlossen', stats)
        return {'status': 'success', 'year': year, 'month': month, **stats}
    except Exception as e:
        log_system_event('ERROR', 'SageCloudImport', 
            f'Zeiterfassungs-Import fehlgeschlagen: {str(e)}')
        raise self.retry(exc=e, countdown=300)
