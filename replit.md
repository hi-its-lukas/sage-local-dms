# Dokumentenmanagementsystem (DMS)

Ein produktionsreifes Django-basiertes Dokumentenmanagementsystem für HR- und Unternehmensabläufe mit Sage HR Cloud und Microsoft 365 Integration.

## Übersicht

Dieses DMS bietet verschlüsselte Dokumentenspeicherung, Multi-Kanal-Eingabeverarbeitung, Sage Cloud Synchronisation und Microsoft 365 E-Mail-Integration. Alle Dokumente werden mit Fernet-Verschlüsselung vor der Speicherung verschlüsselt.

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
  │   └── sage_cloud.py   # Sage Cloud REST API Client
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

### Sage Cloud Integration

**Sage HR Cloud (REST API):**
- Urlaubsanträge importieren → PDF generieren
- Arbeitszeitnachweise → monatliche PDF-Berichte
- Mitarbeiter-Synchronisation
- Idempotente Verarbeitung

### Automatische PDF-Generierung

Das System generiert automatisch professionelle PDF-Dokumente:
- Urlaubsanträge mit Genehmigungsstatus
- Monatliche Arbeitszeitnachweise

### GUI-Konfiguration

Alle Einstellungen sind über Django Admin konfigurierbar:
- **Systemeinstellungen**: Sage Cloud/MS Graph Credentials
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

### Samba-Freigaben (Host-basiert)

Das DMS verwendet Host-Samba statt Docker-Samba für bessere Kompatibilität.

**Installation:**
```bash
sudo ./scripts/install_server.sh
```

**Windows-Laufwerke verbinden:**
```powershell
.\scripts\map_shares.ps1
# Oder manuell:
net use S: \\SERVER_IP\sage_archiv /user:dmsuser PASSWORT /persistent:yes
net use M: \\SERVER_IP\manual_scan /user:dmsuser PASSWORT /persistent:yes
```

**Freigaben:**
- `\\server\sage_archiv` (Nur Lesen) - Sage HR legt hier Dokumente ab
- `\\server\manual_scan` (Lesen/Schreiben) - Scanner-Eingabe

## Admin-Konfiguration

Nach dem ersten Login unter `/admin/`:

1. **Systemeinstellungen** konfigurieren:
   - Sage Cloud API URL + Key
   - MS Graph Tenant/Client/Secret

2. **Periodische Aufgaben** (Celery Beat) einrichten:
   - Sage Mitarbeiter-Sync: Täglich 3:00 Uhr
   - Urlaubsanträge-Import: Alle 4 Stunden
   - Zeiterfassung: Monatserster 23:00 Uhr

## Celery-Aufgaben

| Task | Beschreibung |
|------|-------------|
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

## Aktenlogik (d.3 one-Style)

Das DMS unterstützt jetzt eine d.3 one-ähnliche Aktenstruktur für Personalakten:

### Datenmodelle

- **FileCategory**: Hierarchischer Aktenplan mit Aufbewahrungsfristen
- **PersonnelFile**: Personalakte pro Mitarbeiter
- **PersonnelFileEntry**: Dokument-Ablage in Kategorien
- **DocumentVersion**: Versionierung von Dokumenten
- **AccessPermission**: Benutzer-/Gruppenberechtigungen
- **AuditLog**: Revisionssichere Protokollierung

### Aktenplan

48 Standard-Kategorien für HR-Dokumente mit gesetzlichen Aufbewahrungsfristen:
- 01: Bewerbungsunterlagen (6 Jahre ab Austritt)
- 02: Arbeitsvertrag (10 Jahre ab Austritt)
- 03: Persönliche Daten (6 Jahre / SV 30 Jahre)
- 04: Qualifikation & Entwicklung (10 Jahre)
- 05: Vergütung (10 Jahre ab Dokumentdatum)
- 06: Arbeitszeit & Urlaub (3 Jahre)
- 07: Gesundheit & Arbeitsschutz (3-30 Jahre)
- 08: Beurteilung & Feedback (5 Jahre)
- 09: Disziplinarisches (2-3 Jahre)
- 10: Beendigung (10 Jahre ab Austritt)

### Aufbewahrungsfristen

Drei Trigger-Typen:
- **Ab Erstellung**: Frist beginnt mit Dokumenterstellung
- **Ab Austritt**: Frist beginnt mit Beendigung des Arbeitsverhältnisses
- **Ab Dokumentdatum**: Frist beginnt mit Datum auf dem Dokument

### URLs

- `/personnel-files/` - Personalakten-Liste
- `/personnel-files/<uuid>/` - Personalakte Detail mit Ordnerstruktur
- `/employees/` - Mitarbeiter-Liste mit Akte-Status
- `/filing-plan/` - Aktenplan-Übersicht

### Management-Kommando

```bash
python manage.py create_filing_plan
```

## Mandantenfähigkeit (Multi-Tenancy)

Das System unterstützt jetzt mehrere Mandanten, basierend auf der Sage-Archiv-Ordnerstruktur:

### Automatische Mandantenerkennung

- Sage-Archiv-Ordner: `00000001` = Mandant 1, `00000002` = Mandant 2, etc.
- 8-stellige Ordnernamen werden automatisch als Mandanten erkannt
- Neue Mandanten werden beim Scan automatisch angelegt

### Datenmodelle

- **Tenant**: Mandant mit Code, Name, Beschreibung
- **TenantUser**: Benutzer-Mandanten-Zuordnung mit Admin-Flag
- Alle Kernmodelle haben ein `tenant`-Feld: Employee, Document, PersonnelFile, Department, etc.

### Datenisolierung

- Dokumente werden pro Mandant mit eigenem Hash-Check verarbeitet
- Mitarbeiter-Suche berücksichtigt Mandanten-Kontext
- Admin-Oberfläche hat Mandanten-Filter auf allen relevanten Listen

### Admin-Verwaltung

- `/admin/dms/tenant/` - Mandantenverwaltung
- `/admin/dms/tenantuser/` - Benutzer-Mandanten-Zuordnung
- Alle Listen haben Mandanten-Filter

## Paperless-ngx Features

### Tags und Matching Rules

Das System unterstützt jetzt automatische Dokumentklassifizierung:

- **Tag**: Hierarchische Tags mit Farbcodierung und Eltern-Kind-Beziehungen
- **DocumentTag**: Verknüpfung zwischen Dokumenten und Tags mit Zeitstempel
- **MatchingRule**: Automatische Klassifizierung mit verschiedenen Algorithmen:
  - ANY: Ein Wort muss enthalten sein
  - ALL: Alle Wörter müssen enthalten sein
  - EXACT: Exakter Phrasen-Match
  - REGEX: Regulärer Ausdruck
  - FUZZY: Ähnlichkeits-Match

### Bulk-Bearbeitung

- Mehrfachauswahl von Dokumenten mit Checkboxen
- Aktionsleiste für Massenoperationen
- Unterstützte Aktionen: Status setzen, Mitarbeiter zuweisen, Dokumenttyp ändern, Löschen

### Volltext-Suche

- PostgreSQL Full-Text Search mit SearchVector und SearchRank
- Highlighting von Suchtreffern mit `<mark>` Tags
- Ranking nach Relevanz
- AJAX-Unterstützung für Auto-Complete

### Performance-Optimierungen

- Parallele Dokumentverarbeitung mit ThreadPoolExecutor (max 4 Worker)
- Chunked Hash-Berechnung (64KB Chunks) für große Dateien
- Pfad-basierter Deduplizierungs-Cache zur Vermeidung redundanter Hash-Berechnungen
- Batched DB-Updates (alle 10 Dateien statt pro Datei)
- Thread-sichere Zähler mit Lock-Mechanismen

## Zwei-Faktor-Authentifizierung (MFA)

Das System unterstützt jetzt Multi-Faktor-Authentifizierung mit django-mfa3:

### Unterstützte Methoden

- **FIDO2/WebAuthn (Passkeys)**: Windows Hello, Touch ID, Face ID, YubiKey
- **TOTP (Authenticator-Apps)**: Google Authenticator, Microsoft Authenticator, Authy
- **Wiederherstellungscodes**: Backup-Codes für Notfälle

### Konfiguration

```python
# settings.py
MFA_DOMAIN = "ihre-domain.de"  # Für Produktionsserver
MFA_SITE_TITLE = "DMS - Dokumentenmanagementsystem"
MFA_METHODS = ["FIDO2", "TOTP", "recovery"]
MFA_MAX_KEYS_PER_ACCOUNT = 5
```

### URLs

- `/mfa/` - Sicherheitsschlüssel verwalten
- `/mfa/create/FIDO2/` - Passkey einrichten
- `/mfa/create/TOTP/` - Authenticator-App einrichten
- `/mfa/create/recovery/` - Wiederherstellungscodes erstellen

### MFA-Pflicht

Das System erzwingt MFA für alle Benutzer. Nach dem Login werden Benutzer ohne MFA automatisch zur Einrichtung weitergeleitet.

### Docker-Umgebungsvariable

```yaml
environment:
  - MFA_DOMAIN=ihre-domain.de
```

## Letzte Änderungen

- **Sicherheits-Audit Fixes (Januar 2026)**:
  - Fail-secure SECRET_KEY und ALLOWED_HOSTS in Produktion
  - Mandanten-basierte Zugriffskontrolle für alle Dokumenten-Endpoints
  - HTML-Sanitization (bleach) für E-Mail-zu-PDF-Konvertierung
  - Magic Bytes Validierung für Datei-Uploads
  - 100MB Dateigröße-Limit für Verschlüsselung (DoS-Schutz)
  - Thread-sichere SystemSettings mit select_for_update
- **Zwei-Faktor-Authentifizierung (MFA)**: WebAuthn/Passkeys + TOTP mit Pflicht-Durchsetzung
- **Aktenplan-Filter**: Neuer Filter in der Dokumentensuche nach Aktenplan-Kategorie
- **Paperless-ngx Features**: Tags, Matching Rules, Bulk-Bearbeitung, Volltext-Suche
- **Performance-Optimierungen**: Parallele Verarbeitung, Chunked Hashing, Path-Cache
- **Mandantenfähigkeit**: Automatische Erkennung aus Sage-Ordnerstruktur (00000001, 00000002)
- **Aktenlogik (d.3 one-Style)**: Personalakten, Aktenplan, Versionierung, Berechtigungen
- **CSRF_TRUSTED_ORIGINS**: Konfigurierbar über Umgebungsvariable für Cloudflare
- **Samba-Konfiguration über Admin**: Passwort wird verschlüsselt in DB gespeichert
- Management-Kommandos: `initial_setup`, `generate_samba_config`, `create_filing_plan`
- SystemSettings Singleton für GUI-Konfiguration
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
