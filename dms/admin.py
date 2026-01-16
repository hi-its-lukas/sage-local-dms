from django.contrib import admin
from django.utils.html import format_html
from django import forms
from .models import (
    Department, CostCenter, Employee, DocumentType, Document, 
    ProcessedFile, Task, EmailConfig, SystemLog, SystemSettings,
    ImportedLeaveRequest, ImportedTimesheet
)
from .encryption import encrypt_data, decrypt_data


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'created_at']
    search_fields = ['name', 'description']


@admin.register(CostCenter)
class CostCenterAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['code', 'name']


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ['employee_id', 'full_name', 'sage_local_id', 'sage_cloud_id', 'department', 'cost_center', 'is_active']
    list_filter = ['is_active', 'department', 'cost_center']
    search_fields = ['employee_id', 'first_name', 'last_name', 'email', 'sage_local_id', 'sage_cloud_id']
    raw_id_fields = ['user']
    fieldsets = (
        ('Stammdaten', {
            'fields': ('employee_id', 'first_name', 'last_name', 'email')
        }),
        ('Sage-Verknüpfung', {
            'fields': ('sage_local_id', 'sage_cloud_id'),
            'classes': ('collapse',)
        }),
        ('Organisation', {
            'fields': ('department', 'cost_center', 'entry_date', 'exit_date')
        }),
        ('Benutzer', {
            'fields': ('user', 'is_active')
        }),
    )


@admin.register(DocumentType)
class DocumentTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'description', 'retention_days', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'description']


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['title', 'status', 'source', 'employee', 'document_type', 'file_size_display', 'created_at']
    list_filter = ['status', 'source', 'document_type', 'created_at']
    search_fields = ['title', 'original_filename', 'employee__first_name', 'employee__last_name']
    raw_id_fields = ['employee', 'owner']
    readonly_fields = ['id', 'sha256_hash', 'file_size', 'created_at', 'updated_at']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Dokumentinfo', {
            'fields': ('id', 'title', 'original_filename', 'file_extension', 'mime_type')
        }),
        ('Klassifizierung', {
            'fields': ('document_type', 'employee', 'owner', 'status', 'source')
        }),
        ('Metadaten', {
            'fields': ('metadata', 'notes', 'sha256_hash', 'file_size')
        }),
        ('Zeitstempel', {
            'fields': ('created_at', 'updated_at', 'archived_at'),
            'classes': ('collapse',)
        }),
    )
    
    def file_size_display(self, obj):
        if obj.file_size < 1024:
            return f"{obj.file_size} B"
        elif obj.file_size < 1024 * 1024:
            return f"{obj.file_size / 1024:.1f} KB"
        else:
            return f"{obj.file_size / (1024 * 1024):.1f} MB"
    file_size_display.short_description = 'Größe'
    
    actions = ['mark_as_archived', 'mark_as_review_needed']
    
    def mark_as_archived(self, request, queryset):
        queryset.update(status='ARCHIVED')
    mark_as_archived.short_description = "Als archiviert markieren"
    
    def mark_as_review_needed(self, request, queryset):
        queryset.update(status='REVIEW_NEEDED')
    mark_as_review_needed.short_description = "Prüfung erforderlich markieren"


@admin.register(ProcessedFile)
class ProcessedFileAdmin(admin.ModelAdmin):
    list_display = ['sha256_hash_short', 'original_path', 'processed_at', 'document']
    list_filter = ['processed_at']
    search_fields = ['sha256_hash', 'original_path']
    raw_id_fields = ['document']
    readonly_fields = ['sha256_hash', 'original_path', 'processed_at']
    
    def sha256_hash_short(self, obj):
        return f"{obj.sha256_hash[:16]}..."
    sha256_hash_short.short_description = 'SHA-256'


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'status', 'priority', 'assigned_to', 'due_date', 'created_at']
    list_filter = ['status', 'priority', 'created_at']
    search_fields = ['title', 'description']
    raw_id_fields = ['document', 'assigned_to', 'created_by']
    date_hierarchy = 'created_at'
    
    fieldsets = (
        ('Aufgabeninfo', {
            'fields': ('title', 'description', 'document')
        }),
        ('Zuweisung', {
            'fields': ('assigned_to', 'created_by', 'priority', 'status')
        }),
        ('Termine', {
            'fields': ('due_date', 'completed_at', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    readonly_fields = ['created_at', 'updated_at', 'completed_at']
    
    actions = ['mark_as_completed', 'mark_as_open']
    
    def mark_as_completed(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='COMPLETED', completed_at=timezone.now())
    mark_as_completed.short_description = "Als erledigt markieren"
    
    def mark_as_open(self, request, queryset):
        queryset.update(status='OPEN', completed_at=None)
    mark_as_open.short_description = "Als offen markieren"


@admin.register(EmailConfig)
class EmailConfigAdmin(admin.ModelAdmin):
    list_display = ['name', 'target_mailbox', 'target_folder', 'is_active', 'last_sync']
    list_filter = ['is_active']
    search_fields = ['name', 'target_mailbox']
    readonly_fields = ['last_sync']
    
    fieldsets = (
        ('Konfiguration', {
            'fields': ('name', 'tenant_id', 'client_id', 'is_active')
        }),
        ('Postfach-Einstellungen', {
            'fields': ('target_mailbox', 'target_folder')
        }),
        ('Status', {
            'fields': ('last_sync',),
            'classes': ('collapse',)
        }),
    )


@admin.register(SystemLog)
class SystemLogAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'level_colored', 'source', 'message_short']
    list_filter = ['level', 'source', 'timestamp']
    search_fields = ['message', 'source']
    readonly_fields = ['timestamp', 'level', 'source', 'message', 'details']
    date_hierarchy = 'timestamp'
    
    def level_colored(self, obj):
        colors = {
            'DEBUG': 'gray',
            'INFO': 'blue',
            'WARNING': 'orange',
            'ERROR': 'red',
            'CRITICAL': 'darkred',
        }
        color = colors.get(obj.level, 'black')
        return format_html('<span style="color: {};">{}</span>', color, obj.level)
    level_colored.short_description = 'Level'
    
    def message_short(self, obj):
        return obj.message[:100] + '...' if len(obj.message) > 100 else obj.message
    message_short.short_description = 'Nachricht'
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False


class SystemSettingsAdminForm(forms.ModelForm):
    sage_local_api_key = forms.CharField(
        widget=forms.PasswordInput(render_value=True),
        required=False,
        label="Sage Local API-Schlüssel"
    )
    sage_cloud_api_key = forms.CharField(
        widget=forms.PasswordInput(render_value=True),
        required=False,
        label="Sage Cloud API-Schlüssel"
    )
    ms_graph_secret = forms.CharField(
        widget=forms.PasswordInput(render_value=True),
        required=False,
        label="MS Graph Secret"
    )
    samba_password = forms.CharField(
        widget=forms.PasswordInput(render_value=True),
        required=False,
        label="Samba Passwort",
        help_text="Passwort für Netzwerkfreigaben (Sage_Archiv, Manueller_Scan)"
    )
    
    class Meta:
        model = SystemSettings
        exclude = ['encrypted_sage_local_api_key', 'encrypted_sage_cloud_api_key', 'encrypted_ms_graph_secret', 'encrypted_samba_password']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            if self.instance.encrypted_sage_local_api_key:
                try:
                    self.fields['sage_local_api_key'].initial = decrypt_data(bytes(self.instance.encrypted_sage_local_api_key)).decode()
                except Exception:
                    pass
            if self.instance.encrypted_sage_cloud_api_key:
                try:
                    self.fields['sage_cloud_api_key'].initial = decrypt_data(bytes(self.instance.encrypted_sage_cloud_api_key)).decode()
                except Exception:
                    pass
            if self.instance.encrypted_ms_graph_secret:
                try:
                    self.fields['ms_graph_secret'].initial = decrypt_data(bytes(self.instance.encrypted_ms_graph_secret)).decode()
                except Exception:
                    pass
            if self.instance.encrypted_samba_password:
                try:
                    self.fields['samba_password'].initial = decrypt_data(bytes(self.instance.encrypted_samba_password)).decode()
                except Exception:
                    pass
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        sage_local_key = self.cleaned_data.get('sage_local_api_key')
        if sage_local_key:
            instance.encrypted_sage_local_api_key = encrypt_data(sage_local_key.encode())
        
        sage_cloud_key = self.cleaned_data.get('sage_cloud_api_key')
        if sage_cloud_key:
            instance.encrypted_sage_cloud_api_key = encrypt_data(sage_cloud_key.encode())
        
        ms_graph = self.cleaned_data.get('ms_graph_secret')
        if ms_graph:
            instance.encrypted_ms_graph_secret = encrypt_data(ms_graph.encode())
        
        samba_pw = self.cleaned_data.get('samba_password')
        if samba_pw:
            instance.encrypted_samba_password = encrypt_data(samba_pw.encode())
        
        if commit:
            instance.save()
            self._update_samba_config(instance)
        return instance
    
    def _update_samba_config(self, instance):
        """Generate Samba configuration file after saving settings"""
        import os
        from pathlib import Path
        
        if not instance.encrypted_samba_password:
            return
        
        try:
            samba_password = decrypt_data(bytes(instance.encrypted_samba_password)).decode()
            config_dir = Path('/data/runtime')
            config_dir.mkdir(parents=True, exist_ok=True)
            
            env_file = config_dir / '.env.samba'
            with open(env_file, 'w') as f:
                f.write(f"SAMBA_USER={instance.samba_username}\n")
                f.write(f"SAMBA_PASSWORD={samba_password}\n")
            
            os.chmod(env_file, 0o600)
        except Exception:
            pass


@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    form = SystemSettingsAdminForm
    
    fieldsets = (
        ('Sage Local (WCF/SOAP)', {
            'fields': ('sage_local_wsdl_url', 'sage_local_api_user', 'sage_local_api_key', 'sage_local_timeout'),
            'description': 'Verbindungseinstellungen für lokalen Sage Desktop'
        }),
        ('Sage Cloud (REST)', {
            'fields': ('sage_cloud_api_url', 'sage_cloud_api_key'),
            'description': 'Verbindungseinstellungen für Sage Cloud'
        }),
        ('Microsoft Graph', {
            'fields': ('ms_graph_tenant_id', 'ms_graph_client_id', 'ms_graph_secret'),
            'description': 'Verbindungseinstellungen für Microsoft 365'
        }),
        ('Speicherung', {
            'fields': ('document_storage_path',),
        }),
        ('Netzwerkfreigaben (Samba)', {
            'fields': ('samba_username', 'samba_password'),
            'description': 'Zugangsdaten für Windows-Netzwerkfreigaben'
        }),
    )
    
    def has_add_permission(self, request):
        return not SystemSettings.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ImportedLeaveRequest)
class ImportedLeaveRequestAdmin(admin.ModelAdmin):
    list_display = ['sage_request_id', 'employee', 'leave_type', 'start_date', 'end_date', 'days_count', 'imported_at']
    list_filter = ['leave_type', 'start_date', 'imported_at']
    search_fields = ['sage_request_id', 'employee__first_name', 'employee__last_name']
    raw_id_fields = ['employee', 'document']
    readonly_fields = ['sage_request_id', 'raw_data', 'imported_at']
    date_hierarchy = 'start_date'


@admin.register(ImportedTimesheet)
class ImportedTimesheetAdmin(admin.ModelAdmin):
    list_display = ['employee', 'year', 'month', 'total_hours', 'overtime_hours', 'imported_at']
    list_filter = ['year', 'month', 'imported_at']
    search_fields = ['employee__first_name', 'employee__last_name']
    raw_id_fields = ['employee', 'document']
    readonly_fields = ['raw_data', 'imported_at']


admin.site.site_header = 'DMS Administration'
admin.site.site_title = 'Dokumentenmanagementsystem'
admin.site.index_title = 'Verwaltung'
