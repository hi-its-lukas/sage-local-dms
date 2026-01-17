from django import forms
from .models import Document, Employee, DocumentType, Tag


class BulkEditForm(forms.Form):
    """Formular für Massenbearbeitung von Dokumenten (paperless-ngx Style)"""
    
    ACTIONS = [
        ('', '-- Aktion wählen --'),
        ('set_status', 'Status setzen'),
        ('set_employee', 'Mitarbeiter zuweisen'),
        ('set_document_type', 'Dokumenttyp setzen'),
        ('add_tags', 'Tags hinzufügen'),
        ('remove_tags', 'Tags entfernen'),
        ('delete', 'Löschen'),
    ]
    
    action = forms.ChoiceField(
        choices=ACTIONS,
        required=True,
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'bulk-action-select'})
    )
    
    status = forms.ChoiceField(
        choices=[('', '-- Status wählen --')] + list(Document.STATUS_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    employee = forms.ModelChoiceField(
        queryset=Employee.objects.filter(is_active=True),
        required=False,
        empty_label="-- Mitarbeiter wählen --",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    document_type = forms.ModelChoiceField(
        queryset=DocumentType.objects.filter(is_active=True),
        required=False,
        empty_label="-- Dokumenttyp wählen --",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-control'})
    )
    
    document_ids = forms.CharField(
        widget=forms.HiddenInput(),
        required=True
    )
    
    def __init__(self, *args, tenant=None, **kwargs):
        super().__init__(*args, **kwargs)
        if tenant:
            self.fields['employee'].queryset = Employee.objects.filter(
                tenant=tenant, is_active=True
            ).order_by('last_name', 'first_name')
            self.fields['tags'].queryset = Tag.objects.filter(tenant=tenant)


class DocumentEditForm(forms.ModelForm):
    """Form for editing document attributes."""
    
    class Meta:
        model = Document
        fields = ['title', 'employee', 'document_type', 'status', 'notes']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'employee': forms.Select(attrs={'class': 'form-control'}),
            'document_type': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
        }
        labels = {
            'title': 'Titel',
            'employee': 'Mitarbeiter',
            'document_type': 'Dokumenttyp',
            'status': 'Status',
            'notes': 'Notizen',
        }
    
    def __init__(self, *args, **kwargs):
        tenant = kwargs.pop('tenant', None)
        super().__init__(*args, **kwargs)
        
        if tenant:
            self.fields['employee'].queryset = Employee.objects.filter(
                tenant=tenant, is_active=True
            ).order_by('last_name', 'first_name')
        else:
            self.fields['employee'].queryset = Employee.objects.filter(
                is_active=True
            ).order_by('last_name', 'first_name')
        
        self.fields['employee'].required = False
        self.fields['employee'].empty_label = "-- Nicht zugewiesen --"
        
        self.fields['document_type'].queryset = DocumentType.objects.filter(is_active=True)
        self.fields['document_type'].required = False
        self.fields['document_type'].empty_label = "-- Nicht zugewiesen --"
        
        self.fields['notes'].required = False
