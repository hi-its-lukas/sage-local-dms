#!/usr/bin/env python
"""
DMS Setup-Skript
Generiert automatisch alle notwendigen Schlüssel und Konfigurationen.

Alle weiteren Einstellungen (Sage, Samba, etc.) werden über das
Admin-Interface konfiguriert - keine manuelle .env-Bearbeitung nötig!
"""
import os
import sys
import secrets
import string
from pathlib import Path

def generate_secret_key(length=50):
    """Generiert einen sicheren Django Secret Key."""
    chars = string.ascii_letters + string.digits + '!@#$%^&*(-_=+)'
    return ''.join(secrets.choice(chars) for _ in range(length))

def generate_fernet_key():
    """Generiert einen Fernet-Verschlüsselungsschlüssel."""
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode()

def generate_password(length=16):
    """Generiert ein sicheres Passwort."""
    chars = string.ascii_letters + string.digits + '!@#$%^&*()'
    return ''.join(secrets.choice(chars) for _ in range(length))

def create_env_file():
    """Erstellt die minimale .env Datei - nur technische Grundkonfiguration."""
    env_path = Path('.env')
    
    if env_path.exists():
        print("WARNUNG: .env Datei existiert bereits!")
        response = input("Überschreiben? (j/n): ").lower()
        if response != 'j':
            print("Setup abgebrochen.")
            return False
    
    django_secret = generate_secret_key()
    encryption_key = generate_fernet_key()
    db_password = generate_password(20)
    
    env_content = f"""# DMS Konfiguration - Automatisch generiert
# Technische Grundkonfiguration - NICHT MANUELL BEARBEITEN
# Alle Benutzereinstellungen werden über Admin > Systemeinstellungen konfiguriert

# Django Einstellungen
DJANGO_SECRET_KEY={django_secret}
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1

# Datenbank
POSTGRES_DB=dms
POSTGRES_USER=dms_user
POSTGRES_PASSWORD={db_password}
DATABASE_URL=postgresql://dms_user:{db_password}@db:5432/dms

# Verschlüsselung
ENCRYPTION_KEY={encryption_key}

# Redis
REDIS_URL=redis://redis:6379/0

# Pfade
SAGE_ARCHIVE_PATH=/data/sage_archive
MANUAL_INPUT_PATH=/data/manual_input
EMAIL_ARCHIVE_PATH=/data/email_archive
"""
    
    with open(env_path, 'w') as f:
        f.write(env_content)
    
    return True

def create_directories():
    """Erstellt die notwendigen Verzeichnisse."""
    dirs = [
        'data/sage_archive',
        'data/manual_input',
        'data/manual_input/processed',
        'data/email_archive',
        'data/runtime',
    ]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)
    print("Verzeichnisse erstellt.")

def create_initial_samba_config():
    """Erstellt eine initiale Samba-Konfiguration."""
    runtime_dir = Path('data/runtime')
    runtime_dir.mkdir(parents=True, exist_ok=True)
    
    env_file = runtime_dir / '.env.samba'
    if not env_file.exists():
        with open(env_file, 'w') as f:
            f.write("SAMBA_USER=dmsuser\n")
            f.write("SAMBA_PASSWORD=changeme\n")
        os.chmod(env_file, 0o600)
        print("Initiale Samba-Konfiguration erstellt (bitte über Admin ändern).")

def main():
    print("\n" + "="*60)
    print("DMS - Document Management System Setup")
    print("="*60 + "\n")
    
    create_directories()
    create_initial_samba_config()
    
    if create_env_file():
        print("\n" + "="*60)
        print("SETUP ABGESCHLOSSEN")
        print("="*60)
        print("\nNächste Schritte:")
        print("")
        print("1. Docker starten:")
        print("   docker-compose up -d")
        print("")
        print("2. Ersteinrichtung ausführen (erstellt Admin + Passwörter):")
        print("   docker-compose exec web python manage.py initial_setup")
        print("")
        print("3. Browser öffnen: http://localhost")
        print("   Mit den angezeigten Zugangsdaten anmelden")
        print("")
        print("4. Admin > Systemeinstellungen:")
        print("   - Samba-Passwort ändern")
        print("   - Sage Local/Cloud konfigurieren")
        print("   - Microsoft 365 einrichten")
        print("")
        print("WICHTIG: Alle Einstellungen werden über das Admin-Interface")
        print("konfiguriert - keine manuelle Bearbeitung von Dateien nötig!")
        print("="*60)

if __name__ == '__main__':
    main()
