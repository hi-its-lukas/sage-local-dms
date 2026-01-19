import os
import hashlib
from cryptography.fernet import Fernet
from django.conf import settings


def get_encryption_key():
    key = settings.ENCRYPTION_KEY
    if not key:
        key = os.environ.get('ENCRYPTION_KEY')
    if not key:
        raise ValueError("ENCRYPTION_KEY environment variable is not set. Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
    if isinstance(key, str):
        key = key.encode()
    return key


def get_fernet():
    return Fernet(get_encryption_key())


def encrypt_data(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    fernet = get_fernet()
    return fernet.encrypt(data)


def decrypt_data(encrypted_data):
    if isinstance(encrypted_data, memoryview):
        encrypted_data = bytes(encrypted_data)
    fernet = get_fernet()
    return fernet.decrypt(encrypted_data)


def calculate_sha256(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def calculate_sha256_chunked(file_path, chunk_size=65536):
    """
    Berechnet SHA256 eines Files per Streaming ohne gesamte Datei in RAM zu laden.
    Paperless-ngx-Style: 64KB Chunks für optimale Performance.
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


# SECURITY: Maximale Dateigröße für Verschlüsselung (100 MB)
# Fernet lädt alles in den RAM, daher muss ein Limit gesetzt werden
MAX_ENCRYPTION_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


def encrypt_file(file_path):
    """
    Verschlüsselt eine Datei und berechnet den Hash.
    
    WARNUNG: Lädt die gesamte Datei in den Speicher.
    Für große Dateien encrypt_file_streaming verwenden.
    
    Raises: ValueError wenn Datei zu groß ist
    """
    # SECURITY: Dateigröße prüfen bevor in RAM geladen wird
    file_stats = os.stat(file_path)
    if file_stats.st_size > MAX_ENCRYPTION_FILE_SIZE:
        raise ValueError(
            f"Datei zu groß für Verschlüsselung ({file_stats.st_size / 1024 / 1024:.1f} MB). "
            f"Maximum: {MAX_ENCRYPTION_FILE_SIZE / 1024 / 1024:.0f} MB"
        )
    
    with open(file_path, 'rb') as f:
        data = f.read()
    return encrypt_data(data), calculate_sha256(data)


def encrypt_file_streaming(file_path, chunk_size=1048576):
    """
    Verschlüsselt Datei und berechnet Hash in einem Durchgang.
    1MB Chunks für Verschlüsselung, 64KB für Hash.
    
    WARNUNG: Fernet unterstützt kein echtes Streaming.
    Die gesamte Datei wird in den Speicher geladen.
    Dateigröße wird vorher geprüft.
    
    Returns: (encrypted_bytes, sha256_hash, file_size)
    
    Raises: ValueError wenn Datei zu groß ist
    """
    # SECURITY: Dateigröße prüfen bevor in RAM geladen wird
    file_stats = os.stat(file_path)
    if file_stats.st_size > MAX_ENCRYPTION_FILE_SIZE:
        raise ValueError(
            f"Datei zu groß für Verschlüsselung ({file_stats.st_size / 1024 / 1024:.1f} MB). "
            f"Maximum: {MAX_ENCRYPTION_FILE_SIZE / 1024 / 1024:.0f} MB"
        )
    
    sha256_hash = hashlib.sha256()
    chunks = []
    file_size = 0
    
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            sha256_hash.update(chunk)
            chunks.append(chunk)
            file_size += len(chunk)
    
    content = b''.join(chunks)
    encrypted = encrypt_data(content)
    
    return encrypted, sha256_hash.hexdigest(), file_size


def decrypt_to_bytes(encrypted_data):
    return decrypt_data(encrypted_data)
