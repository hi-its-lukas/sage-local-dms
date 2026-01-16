import os
from pathlib import Path
from django.core.management.base import BaseCommand
from dms.models import SystemSettings
from dms.encryption import decrypt_data


class Command(BaseCommand):
    help = 'Generiert die Samba-Konfigurationsdatei aus den Systemeinstellungen'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            default='/data/runtime',
            help='Ausgabeverzeichnis für die Samba-Konfiguration'
        )

    def handle(self, *args, **options):
        output_dir = Path(options['output_dir'])
        output_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            settings = SystemSettings.load()
            
            if not settings.encrypted_samba_password:
                self.stdout.write(self.style.WARNING(
                    'Kein Samba-Passwort konfiguriert. Bitte in Admin-Einstellungen festlegen.'
                ))
                return
            
            samba_password = decrypt_data(bytes(settings.encrypted_samba_password)).decode()
            
            env_file = output_dir / '.env.samba'
            with open(env_file, 'w') as f:
                f.write(f"SAMBA_USER={settings.samba_username}\n")
                f.write(f"SAMBA_PASSWORD={samba_password}\n")
            
            os.chmod(env_file, 0o600)
            
            self.stdout.write(self.style.SUCCESS(
                f'Samba-Konfiguration erfolgreich erstellt: {env_file}'
            ))
            self.stdout.write(f'Benutzername: {settings.samba_username}')
            self.stdout.write('Hinweis: Nach Passwortänderung "docker-compose restart samba" ausführen')
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Fehler: {str(e)}'))
