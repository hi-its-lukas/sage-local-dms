# Dokumentenmanagementsystem (DMS)

Ein produktionsreifes Django-basiertes Dokumentenmanagementsystem für HR- und Unternehmensabläufe mit Sage HR Suite und Microsoft 365 Integration.

## Übersicht

Dieses DMS bietet verschlüsselte Dokumentenspeicherung, Multi-Kanal-Eingabeverarbeitung, Sage Local/Cloud Synchronisation und Microsoft 365 E-Mail-Integration. Alle Dokumente werden mit Fernet-Verschlüsselung vor der Speicherung verschlüsselt.

## Projektstruktur

```
dms_project/           # Django-Projekteinstellungen
  ├── settings.py      # Hauptkonfiguration
  ├── celery.py        # Celery-Async-Task-Konfiguration
  └── urls.py          # URL-Routing

dms/                   # Hauptanwendung
  ├── models.py        # Datenbankmodelle
  ├── views.py         # Web-Views
  ├── tasks.py         # Celery-Hintergrundaufgaben
  ├── admin.py         # Django-Admin-Konfiguration
  ├── encryption.py    # Fernet-Verschlüsselungstools
  ├── connectors/      # Sage Konnektoren
  │   ├── sage_local.py   # WCF/SOAP Client
  │   └── sage_cloud.py   # REST API Client
  └── generators/      # Dokumentgeneratoren
      └── pdf_generator.py  # PDF-Erstellung

templates/dms/         # HTML-Vorlagen
data/                  # Datenverzeichnisse
  ├── sage_archive/    # Sage HR-Archiv
  ├── manual_input/    # Manueller Scan-Eingabeordner
  └── email_archive/   # E-Mail-Speicher
```

## Hauptfunktionen

### Eingabekanäle

1. **Sage HR-Archiv (Kanal A)**: Idempotenter Import mit SHA-256-Hash-Prüfung
2. **Manuelle Eingabe (Kanal B)**: Verbrauchen-und-Verschieben für Scanner
3. **Web-Upload (Kanal C)**: Drag-and-Drop-Oberfläche
4. **E-Mail (Kanal D)**: Microsoft Graph Integration

### Sage Integration

**Sage Local (WCF/SOAP):**
- Mitarbeiter-Stammdaten synchronisieren
- Abteilungen und Kostenstellen
- Automatisches Mapping von Sage-IDs

**Sage Cloud (REST):**
- Urlaubsanträge importieren → PDF generieren
- Arbeitszeitnachweise → monatliche PDF-Berichte
- Idempotente Verarbeitung

### Automatische PDF-Generierung

Das System generiert automatisch professionelle PDF-Dokumente:
- Urlaubsanträge mit Genehmigungsstatus
- Monatliche Arbeitszeitnachweise

### GUI-Konfiguration

Alle Einstellungen sind über Django Admin konfigurierbar:
- **Systemeinstellungen**: Sage Local/Cloud/MS Graph Credentials
- **Celery Beat**: Cron-Zeitpläne für automatische Synchronisation

### Sicherheit

- Fernet-Verschlüsselung für alle Dateien
- Verschlüsselte API-Schlüssel in der Datenbank
- Passwortschutz für die gesamte Anwendung
- Rollenbasierte Zugriffssteuerung

## Docker-Installation

### Schnellstart

```bash
# 1. Setup ausführen (generiert alle Schlüssel)
python setup.py

# 2. Docker starten
docker-compose up -d

# 3. Browser öffnen: http://localhost
```

### Samba-Freigaben

- `\\server\Sage_Archiv` (Nur Lesen)
- `\\server\Manueller_Scan` (Lesen/Schreiben)

## Admin-Konfiguration

Nach dem ersten Login unter `/admin/`:

1. **Systemeinstellungen** konfigurieren:
   - Sage Local WSDL URL
   - Sage Cloud API URL + Key
   - MS Graph Tenant/Client/Secret

2. **Periodische Aufgaben** (Celery Beat) einrichten:
   - Sage Mitarbeiter-Sync: Täglich 3:00 Uhr
   - Urlaubsanträge-Import: Alle 4 Stunden
   - Zeiterfassung: Monatserster 23:00 Uhr

## Celery-Aufgaben

| Task | Beschreibung |
|------|-------------|
| `sync_sage_local_employees` | Mitarbeiter von Sage Local sync |
| `import_sage_cloud_leave_requests` | Urlaubsanträge importieren |
| `import_sage_cloud_timesheets` | Zeiterfassung des Vormonats |
| `scan_sage_archive` | Sage-Archiv scannen |
| `scan_manual_input` | Manuelle Eingabe verarbeiten |
| `poll_email_inbox` | E-Mail-Postfach abfragen |

## Entwicklung (Replit)

### Zugangsdaten
- Admin URL: `/admin/`
- Benutzername: `admin`
- Passwort: `admin123`

### Celery starten
```bash
celery -A dms_project worker -l INFO
celery -A dms_project beat -l INFO
```

## Letzte Änderungen

- **Samba-Konfiguration über Admin**: Passwort wird verschlüsselt in DB gespeichert
- Management-Kommandos: `initial_setup`, `generate_samba_config`
- SystemSettings Singleton für GUI-Konfiguration
- Sage Local WCF Connector (zeep)
- Sage Cloud REST Connector
- PDF-Generator für Urlaubsanträge und Zeitnachweise
- CostCenter und erweiterte Employee-Felder
- ImportedLeaveRequest/ImportedTimesheet Tracking

## Benutzerfreundliche Einrichtung

Keine Bearbeitung von .env-Dateien nötig! Alle Einstellungen über Admin:

1. **python setup.py** - Erstellt technische Grundkonfiguration
2. **docker-compose up -d** - Startet alle Container
3. **docker-compose exec web python manage.py initial_setup** - Erstellt Admin + Passwörter
4. **Admin > Systemeinstellungen** - Alle weiteren Konfigurationen
