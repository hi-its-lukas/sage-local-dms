import os
import logging
import magic
from pathlib import Path
from datetime import datetime
import redis
from contextlib import contextmanager

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import Document, ProcessedFile, Employee, Task, EmailConfig, SystemLog, Tenant, ScanJob
from .encryption import encrypt_data, decrypt_data, calculate_sha256, encrypt_file
from .ocr import process_document_with_ocr, classify_document, extract_employee_info
import re

logger = logging.getLogger('dms')

_redis_client = None

def get_redis_client():
    global _redis_client
    if _redis_client is None:
        redis_url = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
        _redis_client = redis.from_url(redis_url)
    return _redis_client

@contextmanager
def distributed_lock(lock_name, timeout=3600):
    """
    Redis-basierter verteilter Lock mit SETNX (atomar).
    Verhindert, dass zwei Celery-Worker gleichzeitig denselben Job starten.
    """
    import uuid
    client = get_redis_client()
    lock_key = f"dms:lock:{lock_name}"
    lock_value = str(uuid.uuid4())
    
    # SETNX ist atomar - nur EIN Client kann erfolgreich setzen
    acquired = client.set(lock_key, lock_value, nx=True, ex=timeout)
    
    try:
        yield bool(acquired)
    finally:
        if acquired:
            # Nur löschen wenn wir den Lock besitzen (Lua-Script für Atomarität)
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            try:
                client.eval(lua_script, 1, lock_key, lock_value)
            except Exception:
                pass


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


def extract_employee_from_datamatrix(file_path, max_pages=1, timeout_seconds=10):
    """
    Extrahiert DataMatrix-Codes aus einem PDF.
    Optimiert: Nur erste Seite scannen, mit Timeout.
    
    Returns:
        dict with keys:
            'success': bool - True if processing succeeded
            'error': str or None - Error message if failed
            'codes': list - List of extracted code data
            'employee_ids': list - Parsed employee IDs from codes
    """
    import signal
    
    result = {
        'success': False,
        'error': None,
        'codes': [],
        'employee_ids': []
    }
    
    def timeout_handler(signum, frame):
        raise TimeoutError("DataMatrix extraction timed out")
    
    try:
        import fitz
        from pylibdmtx.pylibdmtx import decode
        from PIL import Image
        import io
        
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout_seconds)
        
        try:
            doc = fitz.open(file_path)
            pages_to_scan = min(len(doc), max_pages)
            
            for page_num in range(pages_to_scan):
                page = doc[page_num]
                pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                
                decoded = decode(img)
                for d in decoded:
                    raw_data = d.data.decode('utf-8')
                    result['codes'].append({'page': page_num, 'raw': raw_data})
                    
                    emp_id = parse_employee_id_from_datamatrix(raw_data)
                    if emp_id and emp_id not in result['employee_ids']:
                        result['employee_ids'].append(emp_id)
                
                if result['employee_ids']:
                    break
            
            doc.close()
            result['success'] = True
            
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        
        return result
        
    except TimeoutError:
        logger.warning(f"DataMatrix extraction timed out for {file_path}")
        result['error'] = 'Timeout'
        result['success'] = True
        return result
    except Exception as e:
        logger.warning(f"DataMatrix extraction failed for {file_path}: {e}")
        result['error'] = str(e)
        return result


def parse_employee_id_from_datamatrix(raw_data):
    """
    Parst die Mitarbeiter-ID aus den DataMatrix-Rohdaten.
    Sage DataMatrix kann verschiedene Formate haben.
    """
    if not raw_data:
        return None
    
    raw_data = raw_data.strip()
    
    if raw_data.isdigit():
        return raw_data
    
    patterns = [
        r'PersNr[:\s]*(\d+)',
        r'Personalnummer[:\s]*(\d+)',
        r'MA[:\s]*(\d+)',
        r'^(\d{4,8})$',
        r'\|(\d+)\|',
        r';(\d+);',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, raw_data, re.IGNORECASE)
        if match:
            return match.group(1)
    
    parts = re.split(r'[|;,\s]+', raw_data)
    for part in parts:
        if part.isdigit() and 3 <= len(part) <= 10:
            return part
    
    return None


def find_employee_by_id(employee_id, tenant=None):
    """
    Sucht einen Mitarbeiter anhand der ID.
    Versucht verschiedene ID-Formate.
    """
    if not employee_id:
        return None
    
    try:
        queryset = Employee.objects.all()
        if tenant:
            queryset = queryset.filter(tenant=tenant)
        
        employee = queryset.filter(employee_id=employee_id).first()
        if employee:
            return employee
        
        if employee_id.isdigit():
            employee = queryset.filter(employee_id=employee_id.lstrip('0')).first()
            if employee:
                return employee
            employee = queryset.filter(employee_id=employee_id.zfill(8)).first()
            if employee:
                return employee
        
        return None
    except Exception:
        return None


SAGE_DOCUMENT_TYPES = {
    'LOHNSCHEINE': {
        'patterns': ['Lohnscheine', 'Korrekturlohnscheine'],
        'is_personnel': True,
        'category': '05.01',
        'description': 'Lohnabrechnung'
    },
    'LOHNSTEUERBESCHEINIGUNG': {
        'patterns': ['Elektronische Lohnsteuerbescheinigung', 'Lohnsteuerbescheinigung'],
        'is_personnel': True,
        'category': '05.02',
        'description': 'Lohnsteuerbescheinigung'
    },
    'MELDEBESCHEINIGUNG': {
        'patterns': ['Meldebescheinigung'],
        'is_personnel': True,
        'category': '03.03',
        'description': 'SV-Meldebescheinigung'
    },
    'ENTGELTBESCHEINIGUNG': {
        'patterns': ['Entgeltbescheinigung'],
        'is_personnel': True,
        'category': '07.01',
        'description': 'Entgeltbescheinigung'
    },
    'BEITRAGSNACHWEIS': {
        'patterns': ['Beitragsnachweis', 'Protokoll Beitragsnachweis'],
        'is_personnel': False,
        'category': '05.03',
        'description': 'Beitragsnachweis'
    },
    'LOHNSTEUERANMELDUNG': {
        'patterns': ['Lohnsteueranmeldung'],
        'is_personnel': False,
        'category': '05.02',
        'description': 'Lohnsteueranmeldung'
    },
    'FIBU': {
        'patterns': ['Fibu-Journal', 'Fibu-Buchungsjournal'],
        'is_personnel': False,
        'category': '05.04',
        'description': 'Fibu-Buchungen'
    },
    'LOHNJOURNAL': {
        'patterns': ['Lohnjournal', 'Jahreslohnjournal'],
        'is_personnel': False,
        'category': '05.01',
        'description': 'Lohnjournal'
    },
    'LOHNKONTO': {
        'patterns': ['Lohnkonto', 'Jahreslohnkonto', 'erweitertes Lohnkonto'],
        'is_personnel': True,
        'category': '05.01',
        'description': 'Lohnkonto'
    },
    'BERUFSGENOSSENSCHAFT': {
        'patterns': ['Berufsgenossenschaftsliste', 'Jahreslohnnachweis Berufsgenossenschaft'],
        'is_personnel': False,
        'category': '07.02',
        'description': 'Berufsgenossenschaft'
    },
    'ELSTAM': {
        'patterns': ['ELStAM'],
        'is_personnel': False,
        'category': '05.02',
        'description': 'ELStAM-Meldung'
    },
    'ERSTATTUNG': {
        'patterns': ['Erstattungsantrag'],
        'is_personnel': False,
        'category': '07.01',
        'description': 'Erstattungsantrag'
    },
    'KUG': {
        'patterns': ['Saison-KUG', 'Saison-Kug'],
        'is_personnel': False,
        'category': '06.03',
        'description': 'Kurzarbeitergeld'
    },
    'STUNDENKALENDARIUM': {
        'patterns': ['Stundenkalendarium', 'Soll-Istprotokoll'],
        'is_personnel': False,
        'category': '06.02',
        'description': 'Zeitnachweis'
    },
    'ZVK': {
        'patterns': ['ZVK-LAK'],
        'is_personnel': False,
        'category': '05.03',
        'description': 'ZVK-Beitragsliste'
    },
    'DIFFERENZABRECHNUNG': {
        'patterns': ['Differenzabrechnung'],
        'is_personnel': False,
        'category': '05.01',
        'description': 'Differenzabrechnung'
    },
    'RESTURLAUB': {
        'patterns': ['Resturlaub'],
        'is_personnel': False,
        'category': '06.01',
        'description': 'Urlaubsübersicht'
    },
    'LST_JAHRESAUSGLEICH': {
        'patterns': ['LSt-Jahresausgleich'],
        'is_personnel': False,
        'category': '05.02',
        'description': 'Lohnsteuer-Jahresausgleich'
    },
    'BUCHUNGSSTAPEL': {
        'patterns': ['EXTF_Buchungsstapel', 'Buchungsstapel'],
        'is_personnel': False,
        'category': '05.04',
        'description': 'DATEV-Export'
    },
    'SAGE_EXPORT': {
        'patterns': ['E_Sage_'],
        'is_personnel': False,
        'category': '05.04',
        'description': 'Sage-Export'
    },
}


def classify_sage_document(filename):
    """
    Klassifiziert ein Sage-Dokument anhand des Dateinamens.
    Gibt (doc_type, is_personnel, category, description) zurück.
    """
    for doc_type, config in SAGE_DOCUMENT_TYPES.items():
        for pattern in config['patterns']:
            if pattern.lower() in filename.lower():
                return (
                    doc_type,
                    config['is_personnel'],
                    config['category'],
                    config['description']
                )
    return ('UNBEKANNT', False, None, 'Unbekanntes Dokument')


@shared_task(bind=True, max_retries=3)
def scan_sage_archive(self):
    """
    Scannt das Sage-Archiv und importiert Dokumente.
    
    Wichtig: Dateien bleiben im Originalordner - nur Hash wird gespeichert.
    Struktur: sage_archiv/00000001/YYYYMM/Dateiname.pdf
    - 00000001 = Mandantenkennung
    - YYYYMM = Abrechnungsmonat
    
    Personalunterlagen (Lohnscheine, etc.) werden via DataMatrix-Code getrennt.
    Firmendokumente (Beitragsnachweis, etc.) werden nach Dateiname klassifiziert.
    """
    with distributed_lock('sage_scanner', timeout=7200) as acquired:
        if not acquired:
            log_system_event('INFO', 'SageScanner', "Scan übersprungen - Redis-Lock aktiv")
            return {'status': 'skipped', 'message': 'Another scan is already running (Redis lock)'}
        
        return _run_sage_scan(self)


def _run_sage_scan(task_self):
    """Eigentliche Scan-Logik, nur ausgeführt wenn Lock erhalten."""
    scan_job = ScanJob.objects.create(
        source='SAGE',
        status='RUNNING',
        total_files=0
    )
    
    sage_path = Path(settings.SAGE_ARCHIVE_PATH)
    
    if not sage_path.exists():
        log_system_event('WARNING', 'SageScanner', f"Sage archive path does not exist: {sage_path}")
        scan_job.status = 'FAILED'
        scan_job.save(update_fields=['status'])
        return {'status': 'error', 'message': 'Path does not exist'}
    
    supported_extensions = {'.pdf', '.doc', '.docx', '.xls', '.xlsx', '.jpg', '.jpeg', '.png', '.tiff', '.txt', '.csv'}
    skip_files = {'thumbs.db', 'desktop.ini', '.ds_store'}
    tenant_folder_pattern = re.compile(r'^\d{8}$')
    month_folder_pattern = re.compile(r'^\d{6}$')
    
    # Phase 1: Alle bekannten Hashes aus DB laden (pro Mandant) - nur Hashes, kein Inhalt
    log_system_event('INFO', 'SageScanner', "Lade bekannte Dateien aus Datenbank...")
    known_hashes_by_tenant = {}
    for tenant in Tenant.objects.filter(is_active=True):
        known_hashes_by_tenant[tenant.code] = set(
            ProcessedFile.objects.filter(tenant=tenant).values_list('sha256_hash', flat=True)
        )
    
    # Phase 2: Nur Dateipfade und neue Dateien ZÄHLEN (ohne Inhalt zu speichern!)
    new_file_paths = []  # Liste von (file_path, tenant_code) - KEIN Inhalt!
    already_processed_count = 0
    
    scan_job.current_file = "Scanne Verzeichnis..."
    scan_job.save(update_fields=['current_file'])
    
    for tenant_folder in sage_path.iterdir():
        if not tenant_folder.is_dir() or not tenant_folder_pattern.match(tenant_folder.name):
            continue
        
        tenant_code = tenant_folder.name
        known_hashes = known_hashes_by_tenant.get(tenant_code, set())
        
        # Mandant erstellen falls nicht vorhanden
        if tenant_code not in known_hashes_by_tenant:
            tenant, created = Tenant.objects.get_or_create(
                code=tenant_code,
                defaults={'name': f'Mandant {tenant_code}', 'is_active': True}
            )
            if created:
                log_system_event('INFO', 'SageScanner', f"Neuer Mandant erstellt: {tenant_code}")
            known_hashes_by_tenant[tenant_code] = set()
            known_hashes = set()
        
        for file_path in tenant_folder.rglob('*'):
            if not file_path.is_file():
                continue
            if file_path.name.lower() in skip_files:
                continue
            if file_path.suffix.lower() not in supported_extensions:
                continue
            
            try:
                # Nur Hash berechnen, Inhalt NICHT im Speicher halten
                with open(file_path, 'rb') as f:
                    content = f.read()
                file_hash = calculate_sha256(content)
                del content  # Sofort freigeben!
                
                if file_hash in known_hashes:
                    already_processed_count += 1
                else:
                    new_file_paths.append((file_path, tenant_code))
            except Exception as e:
                logger.warning(f"Fehler beim Lesen von {file_path}: {e}")
    
    # Nur NEUE Dateien als total_files setzen
    scan_job.total_files = len(new_file_paths)
    scan_job.skipped_files = already_processed_count
    scan_job.save(update_fields=['total_files', 'skipped_files'])
    
    log_system_event('INFO', 'SageScanner', 
        f"Gefunden: {len(new_file_paths)} neue Dateien, {already_processed_count} bereits verarbeitet")
    
    # Wenn keine neuen Dateien, direkt beenden
    if not new_file_paths:
        scan_job.status = 'COMPLETED'
        scan_job.completed_at = timezone.now()
        scan_job.current_file = ''
        scan_job.save()
        return {'status': 'success', 'processed': 0, 'already_processed': already_processed_count}
    
    processed_count = 0
    error_count = 0
    personnel_docs = 0
    company_docs = 0
    
    # Mandanten-Cache für schnellen Zugriff
    tenant_cache = {}
    
    try:
        # Phase 3: Neue Dateien EINZELN verarbeiten (Streaming - kein Vorladen)
        for file_path, tenant_code in new_file_paths:
            # Mandant aus Cache oder DB holen
            if tenant_code not in tenant_cache:
                tenant, _ = Tenant.objects.get_or_create(
                    code=tenant_code,
                    defaults={'name': f'Mandant {tenant_code}', 'is_active': True}
                )
                tenant_cache[tenant_code] = tenant
            
            tenant = tenant_cache[tenant_code]
            
            try:
                # Datei jetzt lesen (Streaming - eine nach der anderen)
                with open(file_path, 'rb') as f:
                    content = f.read()
                file_hash = calculate_sha256(content)
                
                # Nochmal prüfen ob nicht inzwischen verarbeitet (race condition)
                if ProcessedFile.objects.filter(tenant=tenant, sha256_hash=file_hash).exists():
                    already_processed_count += 1
                    scan_job.skipped_files = already_processed_count
                    scan_job.save(update_fields=['skipped_files'])
                    del content
                    continue
                
                # Monatsordner aus Pfad extrahieren
                tenant_folder = sage_path / tenant_code
                month_folder = None
                try:
                    relative_path = file_path.relative_to(tenant_folder)
                    path_parts = relative_path.parts
                    if len(path_parts) >= 2 and month_folder_pattern.match(path_parts[0]):
                        month_folder = path_parts[0]
                except ValueError:
                    pass
                
                # Fortschritt aktualisieren
                scan_job.current_file = file_path.name[:100]
                scan_job.save(update_fields=['current_file'])
                
                encrypted_content = encrypt_data(content)
                mime_type = get_mime_type(str(file_path))
                
                employee = None
                status = 'UNASSIGNED'
                needs_review = False
                dm_result = None
                is_personnel = False
                doc_type = 'UNBEKANNT'
                category = None
                description = 'Unbekanntes Dokument'
                
                if file_path.suffix.lower() == '.pdf':
                    dm_result = extract_employee_from_datamatrix(str(file_path))
                    
                    if dm_result['success'] and dm_result['employee_ids']:
                        is_personnel = True
                        for emp_id in dm_result['employee_ids']:
                            employee = find_employee_by_id(emp_id, tenant=tenant)
                            if employee:
                                status = 'ASSIGNED'
                                break
                        
                        if not employee:
                            needs_review = True
                            status = 'REVIEW_NEEDED'
                        
                        doc_type, _, category, description = classify_sage_document(file_path.name)
                    elif dm_result['success'] and dm_result['codes']:
                        is_personnel = True
                        needs_review = True
                        status = 'REVIEW_NEEDED'
                        doc_type, _, category, description = classify_sage_document(file_path.name)
                    else:
                        doc_type, is_personnel, category, description = classify_sage_document(file_path.name)
                        if is_personnel:
                            needs_review = True
                            status = 'REVIEW_NEEDED'
                        else:
                            status = 'COMPANY'
                else:
                    doc_type, is_personnel, category, description = classify_sage_document(file_path.name)
                    status = 'COMPANY' if not is_personnel else 'UNASSIGNED'
                
                metadata = {
                    'original_path': str(file_path),
                    'needs_review': needs_review,
                    'tenant_code': tenant_code,
                    'doc_type': doc_type,
                    'doc_type_description': description,
                    'is_personnel_document': is_personnel,
                    'category_code': category,
                    'month_folder': month_folder,
                }
                
                if dm_result:
                    metadata['datamatrix'] = {
                        'success': dm_result['success'],
                        'codes_found': len(dm_result['codes']),
                        'employee_ids': dm_result['employee_ids'],
                    }
                
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
                    metadata=metadata
                )
                
                ProcessedFile.objects.create(
                    tenant=tenant,
                    sha256_hash=file_hash,
                    original_path=str(file_path),
                    document=document
                )
                
                # Speicher freigeben
                del content
                del encrypted_content
                
                processed_count += 1
                if is_personnel:
                    personnel_docs += 1
                else:
                    company_docs += 1
                
                scan_job.processed_files = processed_count
                scan_job.save(update_fields=['processed_files'])
                
                if needs_review:
                    log_system_event('WARNING', 'SageScanner', 
                        f"File requires review (DataMatrix issue): {file_path.name}",
                        {'document_id': str(document.id), 'tenant': tenant_code})
                
            except Exception as e:
                error_count += 1
                scan_job.error_files = error_count
                scan_job.save(update_fields=['error_files'])
                log_system_event('ERROR', 'SageScanner', 
                    f"Failed to process file: {file_path.name}",
                    {'error': str(e), 'tenant': tenant_code})
        
        scan_job.status = 'COMPLETED'
        scan_job.completed_at = timezone.now()
        scan_job.processed_files = processed_count
        scan_job.error_files = error_count
        scan_job.current_file = ''
        scan_job.save()
        
        log_system_event('INFO', 'SageScanner', 
            f"Scan abgeschlossen: {processed_count} neu verarbeitet, "
            f"{already_processed_count} bereits vorhanden, {error_count} Fehler")
        
        return {
            'status': 'success',
            'processed': processed_count,
            'personnel_documents': personnel_docs,
            'company_documents': company_docs,
            'already_processed': already_processed_count,
            'errors': error_count
        }
        
    except Exception as e:
        scan_job.status = 'FAILED'
        scan_job.error_message = str(e)
        scan_job.completed_at = timezone.now()
        scan_job.save()
        log_system_event('CRITICAL', 'SageScanner', f"Sage scan failed: {str(e)}")
        raise task_self.retry(exc=e, countdown=60)


@shared_task(bind=True, max_retries=3)
def scan_manual_input(self):
    with distributed_lock('manual_scanner', timeout=3600) as acquired:
        if not acquired:
            log_system_event('INFO', 'ManualScanner', "Scan übersprungen - Redis-Lock aktiv")
            return {'status': 'skipped', 'message': 'Another scan is already running (Redis lock)'}
        
        return _run_manual_scan(self)


def _run_manual_scan(task_self):
    """Eigentliche Manual-Scan-Logik, nur ausgeführt wenn Lock erhalten."""
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
                
                employee = None
                status = 'UNASSIGNED'
                doc_type = 'UNBEKANNT'
                doc_type_confidence = 0.0
                category_suggestion = None
                
                try:
                    ocr_result = process_document_with_ocr(content, mime_type)
                    if ocr_result:
                        ocr_text = ocr_result.get('text', '')[:10000]
                        doc_type = ocr_result.get('doc_type', 'UNBEKANNT')
                        doc_type_confidence = ocr_result.get('doc_type_confidence', 0.0)
                        category_suggestion = ocr_result.get('category_suggestion')
                        
                        if ocr_result.get('employee_info'):
                            emp_info = ocr_result['employee_info']
                            if emp_info.get('employee_id'):
                                employee = find_employee_by_id(emp_info['employee_id'])
                                if employee:
                                    status = 'ASSIGNED'
                                    log_system_event('INFO', 'OCR', 
                                        f"Mitarbeiter via OCR erkannt: {employee.first_name} {employee.last_name}",
                                        {'document': file_path.name, 'employee_id': emp_info['employee_id']})
                except Exception as ocr_error:
                    log_system_event('WARNING', 'OCR', 
                        f"OCR-Verarbeitung fehlgeschlagen: {file_path.name}",
                        {'error': str(ocr_error)})
                    ocr_text = ''
                
                document = Document.objects.create(
                    title=file_path.stem,
                    original_filename=file_path.name,
                    file_extension=file_path.suffix,
                    mime_type=mime_type,
                    encrypted_content=encrypted_content,
                    file_size=len(content),
                    employee=employee,
                    status=status,
                    source='MANUAL',
                    sha256_hash=file_hash,
                    metadata={
                        'original_path': str(file_path),
                        'doc_type': doc_type,
                        'doc_type_confidence': doc_type_confidence,
                        'category_suggestion': category_suggestion,
                        'ocr_text_preview': ocr_text[:500] if ocr_text else ''
                    }
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
                    f"Verarbeitet: {file_path.name} (Typ: {doc_type}, Konfidenz: {doc_type_confidence:.0%})",
                    {'document_id': str(document.id), 'doc_type': doc_type})
                
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
        raise task_self.retry(exc=e, countdown=60)


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
