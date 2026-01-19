#!/bin/bash
set -e

echo "DMS wird gestartet..."

# Warte auf Datenbank
echo "Warte auf Datenbank..."
while ! nc -z db 5432; do
    sleep 1
done
echo "Datenbank ist bereit."

# Migrationen ausführen
echo "Führe Datenbankmigrationen aus..."
python manage.py migrate --noinput

# Statische Dateien sammeln
echo "Sammle statische Dateien..."
python manage.py collectstatic --noinput

# Admin-Benutzer erstellen falls nicht vorhanden
echo "Prüfe Admin-Benutzer..."
python manage.py shell << EOF
from django.contrib.auth.models import User
import os
import sys

username = os.environ.get('ADMIN_USERNAME', 'admin')
password = os.environ.get('ADMIN_PASSWORD', '')
email = os.environ.get('ADMIN_EMAIL', 'admin@example.com')

# SECURITY: Kein Default-Passwort mehr - muss explizit gesetzt werden
if not password:
    print("WARNUNG: ADMIN_PASSWORD nicht gesetzt. Admin wird nicht automatisch erstellt.")
    print("Setzen Sie ADMIN_PASSWORD in der .env Datei oder verwenden Sie 'python manage.py createsuperuser'")
elif password in ['admin123', 'password', '123456', 'admin']:
    print("FEHLER: Unsicheres Standard-Passwort erkannt! Bitte ein sicheres Passwort in ADMIN_PASSWORD setzen.")
    sys.exit(1)
elif not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username, email, password)
    print(f"Admin-Benutzer '{username}' erstellt.")
else:
    print(f"Admin-Benutzer '{username}' existiert bereits.")
EOF

echo "DMS gestartet."

# Starte Gunicorn
exec gunicorn dms_project.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 4 \
    --access-logfile - \
    --error-logfile -
