import secrets
import string
from pathlib import Path
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from dms.models import SystemSettings
from dms.encryption import encrypt_data


class Command(BaseCommand):
    help = 'Ersteinrichtung des DMS - erstellt Admin-Benutzer und Grundkonfiguration'

    def add_arguments(self, parser):
        parser.add_argument(
            '--admin-password',
            help='Admin-Passwort (wird generiert wenn nicht angegeben)'
        )
        parser.add_argument(
            '--samba-password',
            help='Samba-Passwort (wird generiert wenn nicht angegeben)'
        )
        parser.add_argument(
            '--no-interactive',
            action='store_true',
            help='Nicht-interaktiver Modus'
        )

    def generate_password(self, length=12):
        chars = string.ascii_letters + string.digits + '!@#$%^&*()'
        return ''.join(secrets.choice(chars) for _ in range(length))

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('\n=== DMS Ersteinrichtung ===\n'))
        
        admin_exists = User.objects.filter(is_superuser=True).exists()
        if admin_exists:
            self.stdout.write(self.style.WARNING('Admin-Benutzer existiert bereits.'))
        else:
            admin_password = options.get('admin_password') or self.generate_password()
            User.objects.create_superuser(
                username='admin',
                email='admin@example.com',
                password=admin_password
            )
            self.stdout.write(self.style.SUCCESS('Admin-Benutzer erstellt:'))
            self.stdout.write(f'  Benutzername: admin')
            self.stdout.write(f'  Passwort: {admin_password}')
            self.stdout.write('')
        
        settings = SystemSettings.load()
        
        if not settings.encrypted_samba_password:
            samba_password = options.get('samba_password') or self.generate_password()
            settings.encrypted_samba_password = encrypt_data(samba_password.encode())
            settings.save()
            
            self.stdout.write(self.style.SUCCESS('Samba-Zugangsdaten erstellt:'))
            self.stdout.write(f'  Benutzername: {settings.samba_username}')
            self.stdout.write(f'  Passwort: {samba_password}')
            self.stdout.write('')
            
            runtime_dir = Path('/data/runtime')
            runtime_dir.mkdir(parents=True, exist_ok=True)
            env_file = runtime_dir / '.env.samba'
            with open(env_file, 'w') as f:
                f.write(f"SAMBA_USER={settings.samba_username}\n")
                f.write(f"SAMBA_PASSWORD={samba_password}\n")
            import os
            os.chmod(env_file, 0o600)
        else:
            self.stdout.write(self.style.WARNING('Samba-Passwort bereits konfiguriert.'))
        
        data_dirs = [
            'data/sage_archive',
            'data/manual_input',
            'data/manual_input/processed',
            'data/email_archive',
            'data/runtime',
        ]
        for d in data_dirs:
            Path(d).mkdir(parents=True, exist_ok=True)
        
        self.stdout.write(self.style.SUCCESS('\nErsteinrichtung abgeschlossen!'))
        self.stdout.write('\nNächste Schritte:')
        self.stdout.write('1. docker-compose up -d')
        self.stdout.write('2. Browser öffnen: http://localhost')
        self.stdout.write('3. Mit Admin-Zugangsdaten anmelden')
        self.stdout.write('4. Unter Admin > Systemeinstellungen weitere Optionen konfigurieren')
