import uuid
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class CostCenter(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.code} - {self.name}"

    class Meta:
        ordering = ['code']
        verbose_name = "Kostenstelle"
        verbose_name_plural = "Kostenstellen"


class Employee(models.Model):
    employee_id = models.CharField(max_length=50, unique=True, verbose_name="Mitarbeiter-ID")
    sage_local_id = models.CharField(max_length=100, blank=True, null=True, unique=True, verbose_name="Sage Local ID")
    sage_cloud_id = models.CharField(max_length=100, blank=True, null=True, unique=True, verbose_name="Sage Cloud ID")
    first_name = models.CharField(max_length=100, verbose_name="Vorname")
    last_name = models.CharField(max_length=100, verbose_name="Nachname")
    email = models.EmailField(blank=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Abteilung")
    cost_center = models.ForeignKey(CostCenter, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Kostenstelle")
    entry_date = models.DateField(null=True, blank=True, verbose_name="Eintrittsdatum")
    exit_date = models.DateField(null=True, blank=True, verbose_name="Austrittsdatum")
    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='employee_profile')
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.employee_id} - {self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    class Meta:
        ordering = ['last_name', 'first_name']


class DocumentType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    required_fields = models.JSONField(default=dict, blank=True, help_text="JSON schema for required metadata fields")
    retention_days = models.PositiveIntegerField(default=0, help_text="Days to retain document (0 = forever)")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class Document(models.Model):
    STATUS_CHOICES = [
        ('UNASSIGNED', 'Unassigned/Inbox'),
        ('ASSIGNED', 'Assigned'),
        ('ARCHIVED', 'Archived'),
        ('REVIEW_NEEDED', 'Review Needed'),
    ]

    SOURCE_CHOICES = [
        ('SAGE', 'Sage HR Archive'),
        ('MANUAL', 'Manual Input'),
        ('WEB', 'Web Upload'),
        ('EMAIL', 'Email Import'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    original_filename = models.CharField(max_length=255)
    file_extension = models.CharField(max_length=20)
    mime_type = models.CharField(max_length=100, blank=True)
    encrypted_content = models.BinaryField(help_text="Fernet-encrypted file content")
    file_size = models.PositiveIntegerField(default=0)
    
    document_type = models.ForeignKey(DocumentType, on_delete=models.SET_NULL, null=True, blank=True)
    employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='documents')
    owner = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_documents')
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='UNASSIGNED')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='WEB')
    
    metadata = models.JSONField(default=dict, blank=True, help_text="Additional document metadata")
    notes = models.TextField(blank=True)
    
    sha256_hash = models.CharField(max_length=64, db_index=True, help_text="SHA-256 hash of original file")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.title} ({self.status})"

    def archive(self):
        self.status = 'ARCHIVED'
        self.archived_at = timezone.now()
        self.save()

    class Meta:
        ordering = ['-created_at']
        permissions = [
            ("view_all_documents", "Can view all documents"),
            ("manage_documents", "Can manage all documents"),
        ]


class ProcessedFile(models.Model):
    sha256_hash = models.CharField(max_length=64, unique=True, db_index=True)
    original_path = models.CharField(max_length=500)
    processed_at = models.DateTimeField(auto_now_add=True)
    document = models.ForeignKey(Document, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.sha256_hash[:16]}... - {self.original_path}"

    class Meta:
        ordering = ['-processed_at']


class Task(models.Model):
    PRIORITY_CHOICES = [
        (1, 'Low'),
        (2, 'Medium'),
        (3, 'High'),
        (4, 'Urgent'),
    ]

    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='tasks')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tasks')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_tasks')
    
    priority = models.IntegerField(choices=PRIORITY_CHOICES, default=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    
    due_date = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} - {self.get_status_display()}"

    def complete(self):
        self.status = 'COMPLETED'
        self.completed_at = timezone.now()
        self.save()

    class Meta:
        ordering = ['-priority', 'due_date', '-created_at']


class EmailConfig(models.Model):
    name = models.CharField(max_length=100, unique=True)
    tenant_id = models.CharField(max_length=100)
    client_id = models.CharField(max_length=100)
    encrypted_client_secret = models.BinaryField(help_text="Fernet-encrypted client secret")
    target_mailbox = models.EmailField(help_text="Email address to monitor")
    target_folder = models.CharField(max_length=100, default='Inbox')
    is_active = models.BooleanField(default=True)
    last_sync = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.target_mailbox}"

    class Meta:
        verbose_name = "Email Configuration"
        verbose_name_plural = "Email Configurations"


class SystemLog(models.Model):
    LEVEL_CHOICES = [
        ('DEBUG', 'Debug'),
        ('INFO', 'Info'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
        ('CRITICAL', 'Critical'),
    ]

    timestamp = models.DateTimeField(auto_now_add=True)
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, default='INFO')
    source = models.CharField(max_length=100)
    message = models.TextField()
    details = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"[{self.level}] {self.timestamp} - {self.source}"

    class Meta:
        ordering = ['-timestamp']
        verbose_name = "Systemprotokoll"
        verbose_name_plural = "Systemprotokolle"


class SystemSettings(models.Model):
    """Singleton model for system-wide configuration - editable via Django Admin"""
    
    sage_local_wsdl_url = models.URLField(
        blank=True, 
        verbose_name="Sage Local WSDL URL",
        help_text="z.B. http://192.168.x.x:33033/?wsdl"
    )
    sage_local_api_user = models.CharField(max_length=100, blank=True, verbose_name="Sage Local API-Benutzer")
    encrypted_sage_local_api_key = models.BinaryField(blank=True, null=True, verbose_name="Sage Local API-Schlüssel (verschlüsselt)")
    sage_local_timeout = models.PositiveIntegerField(default=30, verbose_name="Sage Local Timeout (Sekunden)")
    
    sage_cloud_api_url = models.URLField(
        blank=True, 
        verbose_name="Sage Cloud API URL",
        help_text="z.B. https://mycompany.sage.hr/api"
    )
    encrypted_sage_cloud_api_key = models.BinaryField(blank=True, null=True, verbose_name="Sage Cloud API-Schlüssel (verschlüsselt)")
    
    ms_graph_tenant_id = models.CharField(max_length=100, blank=True, verbose_name="MS Graph Tenant ID")
    ms_graph_client_id = models.CharField(max_length=100, blank=True, verbose_name="MS Graph Client ID")
    encrypted_ms_graph_secret = models.BinaryField(blank=True, null=True, verbose_name="MS Graph Secret (verschlüsselt)")
    
    document_storage_path = models.CharField(
        max_length=500, 
        default="/data/personalakten",
        verbose_name="Dokumentenspeicherpfad",
        help_text="Basispfad für Personalakten"
    )
    
    samba_username = models.CharField(
        max_length=50, 
        default="dmsuser",
        verbose_name="Samba Benutzername",
        help_text="Benutzername für Netzwerkfreigaben"
    )
    encrypted_samba_password = models.BinaryField(
        blank=True, 
        null=True, 
        verbose_name="Samba Passwort (verschlüsselt)"
    )
    
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Systemeinstellungen"

    class Meta:
        verbose_name = "Systemeinstellung"
        verbose_name_plural = "Systemeinstellungen"


class ImportedLeaveRequest(models.Model):
    """Tracks imported leave requests from Sage Cloud to prevent duplicates"""
    sage_request_id = models.CharField(max_length=100, unique=True, verbose_name="Sage Anfrage-ID")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    document = models.ForeignKey('Document', on_delete=models.SET_NULL, null=True, blank=True)
    
    leave_type = models.CharField(max_length=100, verbose_name="Urlaubsart")
    start_date = models.DateField(verbose_name="Startdatum")
    end_date = models.DateField(verbose_name="Enddatum")
    days_count = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Anzahl Tage")
    approval_date = models.DateField(null=True, blank=True, verbose_name="Genehmigungsdatum")
    approved_by = models.CharField(max_length=200, blank=True, verbose_name="Genehmigt von")
    
    raw_data = models.JSONField(default=dict, verbose_name="Rohdaten")
    imported_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.employee} - {self.leave_type} ({self.start_date} - {self.end_date})"

    class Meta:
        ordering = ['-start_date']
        verbose_name = "Importierter Urlaubsantrag"
        verbose_name_plural = "Importierte Urlaubsanträge"


class ImportedTimesheet(models.Model):
    """Tracks imported monthly timesheets from Sage Cloud"""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='timesheets')
    document = models.ForeignKey('Document', on_delete=models.SET_NULL, null=True, blank=True)
    
    year = models.PositiveIntegerField(verbose_name="Jahr")
    month = models.PositiveIntegerField(verbose_name="Monat")
    
    total_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name="Gesamtstunden")
    overtime_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name="Überstunden")
    
    raw_data = models.JSONField(default=dict, verbose_name="Rohdaten")
    imported_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.employee} - {self.month:02d}/{self.year}"

    class Meta:
        ordering = ['-year', '-month']
        unique_together = ['employee', 'year', 'month']
        verbose_name = "Importierte Zeiterfassung"
        verbose_name_plural = "Importierte Zeiterfassungen"


class FileCategory(models.Model):
    """Aktenplan - Kategorien mit Aufbewahrungsfristen (wie d.3 one)"""
    code = models.CharField(max_length=20, unique=True, verbose_name="Aktenzeichen")
    name = models.CharField(max_length=200, verbose_name="Bezeichnung")
    description = models.TextField(blank=True, verbose_name="Beschreibung")
    parent = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='subcategories',
        verbose_name="Übergeordnete Kategorie"
    )
    
    retention_years = models.PositiveIntegerField(
        default=10, 
        verbose_name="Aufbewahrungsfrist (Jahre)",
        help_text="0 = unbegrenzt"
    )
    retention_trigger = models.CharField(
        max_length=50,
        choices=[
            ('CREATION', 'Ab Erstellung'),
            ('EXIT', 'Ab Austritt'),
            ('DOCUMENT_DATE', 'Ab Dokumentdatum'),
        ],
        default='EXIT',
        verbose_name="Fristbeginn"
    )
    
    is_mandatory = models.BooleanField(default=False, verbose_name="Pflichtakte")
    sort_order = models.PositiveIntegerField(default=0, verbose_name="Sortierung")
    is_active = models.BooleanField(default=True, verbose_name="Aktiv")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.code} - {self.name}"
    
    def get_full_path(self):
        if self.parent:
            return f"{self.parent.get_full_path()} / {self.name}"
        return self.name

    class Meta:
        ordering = ['sort_order', 'code']
        verbose_name = "Aktenkategorie"
        verbose_name_plural = "Aktenkategorien (Aktenplan)"


class PersonnelFile(models.Model):
    """Personalakte - Container für alle Dokumente eines Mitarbeiters"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    employee = models.OneToOneField(
        Employee, 
        on_delete=models.CASCADE, 
        related_name='personnel_file',
        verbose_name="Mitarbeiter"
    )
    
    file_number = models.CharField(
        max_length=50, 
        unique=True, 
        verbose_name="Aktenzeichen",
        help_text="Eindeutige Aktennummer"
    )
    
    STATUS_CHOICES = [
        ('ACTIVE', 'Aktiv'),
        ('INACTIVE', 'Inaktiv (ausgeschieden)'),
        ('ARCHIVED', 'Archiviert'),
        ('DELETED', 'Zur Löschung vorgemerkt'),
    ]
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='ACTIVE',
        verbose_name="Status"
    )
    
    opened_at = models.DateField(auto_now_add=True, verbose_name="Eröffnungsdatum")
    closed_at = models.DateField(null=True, blank=True, verbose_name="Schließungsdatum")
    retention_until = models.DateField(null=True, blank=True, verbose_name="Aufbewahren bis")
    
    notes = models.TextField(blank=True, verbose_name="Bemerkungen")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.file_number} - {self.employee.full_name}"
    
    def document_count(self):
        return self.file_entries.count()
    document_count.short_description = "Dokumente"

    class Meta:
        ordering = ['file_number']
        verbose_name = "Personalakte"
        verbose_name_plural = "Personalakten"


class PersonnelFileEntry(models.Model):
    """Eintrag in einer Personalakte - verknüpft Dokument mit Akte und Kategorie"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel_file = models.ForeignKey(
        PersonnelFile, 
        on_delete=models.CASCADE, 
        related_name='file_entries',
        verbose_name="Personalakte"
    )
    document = models.ForeignKey(
        Document, 
        on_delete=models.CASCADE, 
        related_name='file_entries',
        verbose_name="Dokument"
    )
    category = models.ForeignKey(
        FileCategory, 
        on_delete=models.PROTECT, 
        related_name='file_entries',
        verbose_name="Kategorie"
    )
    
    entry_number = models.PositiveIntegerField(verbose_name="Laufende Nr.")
    entry_date = models.DateField(default=timezone.now, verbose_name="Eintragsdatum")
    document_date = models.DateField(null=True, blank=True, verbose_name="Dokumentdatum")
    
    notes = models.TextField(blank=True, verbose_name="Bemerkungen")
    
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='created_file_entries',
        verbose_name="Erstellt von"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.personnel_file.file_number}/{self.entry_number} - {self.document.title}"

    def save(self, *args, **kwargs):
        if not self.entry_number:
            last_entry = PersonnelFileEntry.objects.filter(
                personnel_file=self.personnel_file
            ).order_by('-entry_number').first()
            self.entry_number = (last_entry.entry_number + 1) if last_entry else 1
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['personnel_file', '-entry_number']
        unique_together = ['personnel_file', 'entry_number']
        verbose_name = "Akteneintrag"
        verbose_name_plural = "Akteneinträge"


class DocumentVersion(models.Model):
    """Dokumentenversion - speichert alle Versionen eines Dokuments"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(
        Document, 
        on_delete=models.CASCADE, 
        related_name='versions',
        verbose_name="Dokument"
    )
    
    version_number = models.PositiveIntegerField(verbose_name="Versionsnummer")
    encrypted_content = models.BinaryField(verbose_name="Verschlüsselter Inhalt")
    file_size = models.PositiveIntegerField(default=0, verbose_name="Dateigröße")
    sha256_hash = models.CharField(max_length=64, verbose_name="SHA-256 Hash")
    
    change_reason = models.CharField(max_length=500, blank=True, verbose_name="Änderungsgrund")
    
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True,
        verbose_name="Erstellt von"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.document.title} v{self.version_number}"

    class Meta:
        ordering = ['document', '-version_number']
        unique_together = ['document', 'version_number']
        verbose_name = "Dokumentenversion"
        verbose_name_plural = "Dokumentenversionen"


class AccessPermission(models.Model):
    """Zugriffsrechte auf Akten und Kategorien"""
    PERMISSION_CHOICES = [
        ('VIEW', 'Ansehen'),
        ('EDIT', 'Bearbeiten'),
        ('DELETE', 'Löschen'),
        ('ADMIN', 'Vollzugriff'),
    ]
    
    TARGET_TYPE_CHOICES = [
        ('CATEGORY', 'Kategorie'),
        ('PERSONNEL_FILE', 'Personalakte'),
        ('DEPARTMENT', 'Abteilung'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='dms_permissions',
        verbose_name="Benutzer"
    )
    group = models.ForeignKey(
        'auth.Group', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='dms_permissions',
        verbose_name="Gruppe"
    )
    
    target_type = models.CharField(
        max_length=20, 
        choices=TARGET_TYPE_CHOICES,
        verbose_name="Zieltyp"
    )
    
    category = models.ForeignKey(
        FileCategory, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='permissions',
        verbose_name="Kategorie"
    )
    personnel_file = models.ForeignKey(
        PersonnelFile, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='permissions',
        verbose_name="Personalakte"
    )
    department = models.ForeignKey(
        Department, 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True,
        related_name='permissions',
        verbose_name="Abteilung"
    )
    
    permission_level = models.CharField(
        max_length=20, 
        choices=PERMISSION_CHOICES, 
        default='VIEW',
        verbose_name="Berechtigungsstufe"
    )
    
    inherit_to_children = models.BooleanField(
        default=True, 
        verbose_name="Auf Unterordner vererben"
    )
    
    valid_from = models.DateField(null=True, blank=True, verbose_name="Gültig ab")
    valid_until = models.DateField(null=True, blank=True, verbose_name="Gültig bis")
    
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name='created_permissions',
        verbose_name="Erstellt von"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        target = self.user or self.group
        obj = self.category or self.personnel_file or self.department
        return f"{target} → {obj}: {self.get_permission_level_display()}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if not self.user and not self.group:
            raise ValidationError("Entweder Benutzer oder Gruppe muss angegeben werden.")
        if self.user and self.group:
            raise ValidationError("Nur Benutzer ODER Gruppe angeben, nicht beides.")

    class Meta:
        ordering = ['target_type', 'permission_level']
        verbose_name = "Zugriffsberechtigung"
        verbose_name_plural = "Zugriffsberechtigungen"


class AuditLog(models.Model):
    """Revisionssichere Protokollierung aller Aktionen"""
    ACTION_CHOICES = [
        ('CREATE', 'Erstellt'),
        ('VIEW', 'Angesehen'),
        ('DOWNLOAD', 'Heruntergeladen'),
        ('EDIT', 'Bearbeitet'),
        ('DELETE', 'Gelöscht'),
        ('ARCHIVE', 'Archiviert'),
        ('RESTORE', 'Wiederhergestellt'),
        ('PERMISSION_CHANGE', 'Berechtigung geändert'),
        ('VERSION_CREATE', 'Version erstellt'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="Zeitstempel")
    
    user = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True,
        verbose_name="Benutzer"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="IP-Adresse")
    user_agent = models.CharField(max_length=500, blank=True, verbose_name="User-Agent")
    
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, verbose_name="Aktion")
    
    document = models.ForeignKey(
        Document, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='audit_logs',
        verbose_name="Dokument"
    )
    personnel_file = models.ForeignKey(
        PersonnelFile, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='audit_logs',
        verbose_name="Personalakte"
    )
    
    details = models.JSONField(default=dict, blank=True, verbose_name="Details")
    old_value = models.TextField(blank=True, verbose_name="Alter Wert")
    new_value = models.TextField(blank=True, verbose_name="Neuer Wert")

    def __str__(self):
        return f"{self.timestamp} - {self.user} - {self.get_action_display()}"

    class Meta:
        ordering = ['-timestamp']
        verbose_name = "Audit-Protokoll"
        verbose_name_plural = "Audit-Protokolle"
