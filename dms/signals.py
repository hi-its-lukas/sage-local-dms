from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from datetime import date
from dateutil.relativedelta import relativedelta


def calculate_entry_retention_date(entry, pf):
    trigger = entry.category.retention_trigger
    years = entry.category.retention_years
    
    if years == 0:
        return None
    
    if trigger == 'EXIT':
        if pf.closed_at:
            return pf.closed_at + relativedelta(years=years)
        return None
    elif trigger == 'CREATION':
        return entry.created_at.date() + relativedelta(years=years)
    elif trigger == 'DOCUMENT_DATE':
        if entry.document_date:
            return entry.document_date + relativedelta(years=years)
        return entry.created_at.date() + relativedelta(years=years)
    
    return None


@receiver(pre_save, sender='dms.PersonnelFile')
def calculate_retention_date(sender, instance, **kwargs):
    if instance.status == 'INACTIVE':
        try:
            entries = instance.file_entries.select_related('category').all()
        except ValueError:
            return
        
        max_retention = None
        
        for entry in entries:
            retention_date = calculate_entry_retention_date(entry, instance)
            if retention_date:
                if not max_retention or retention_date > max_retention:
                    max_retention = retention_date
        
        if max_retention:
            instance.retention_until = max_retention
        elif instance.closed_at:
            instance.retention_until = instance.closed_at + relativedelta(years=10)


@receiver(post_save, sender='dms.PersonnelFileEntry')
def update_personnel_file_retention(sender, instance, created, **kwargs):
    pf = instance.personnel_file
    
    retention_date = calculate_entry_retention_date(instance, pf)
    
    if retention_date:
        if not pf.retention_until or retention_date > pf.retention_until:
            pf.retention_until = retention_date
            pf.save(update_fields=['retention_until'])
