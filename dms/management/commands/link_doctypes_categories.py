"""
Management-Kommando zum Verknüpfen von DocumentTypes mit FileCategories
und zum nachträglichen Ablegen von Dokumenten in Personalakten.

Nutzung:
    python manage.py link_doctypes_categories
    python manage.py link_doctypes_categories --file-existing
"""

from django.core.management.base import BaseCommand
from dms.models import DocumentType, FileCategory, Document, PersonnelFileEntry
from dms.tasks import SAGE_DOCUMENT_TYPES


class Command(BaseCommand):
    help = 'Verknüpft DocumentTypes mit FileCategories basierend auf SAGE_DOCUMENT_TYPES'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file-existing',
            action='store_true',
            help='Legt bestehende Dokumente nachträglich in Personalakten ab',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Zeigt nur an was gemacht würde, ohne Änderungen',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        file_existing = options['file_existing']

        if dry_run:
            self.stdout.write(self.style.WARNING('=== DRY RUN - Keine Änderungen ===\n'))

        self.stdout.write(self.style.MIGRATE_HEADING('DocumentTypes mit FileCategories verknüpfen...\n'))
        
        updated = 0
        created = 0
        errors = []

        for type_name, config in SAGE_DOCUMENT_TYPES.items():
            cat_code = config.get('category')
            description = config.get('description', type_name)
            
            if not cat_code:
                self.stdout.write(f'  {type_name}: Keine Kategorie definiert - übersprungen')
                continue
            
            fc = FileCategory.objects.filter(code=cat_code).first()
            if not fc:
                errors.append(f'FileCategory {cat_code} nicht gefunden für {type_name}')
                continue
            
            dt = DocumentType.objects.filter(name=type_name).first()
            
            if dt:
                if dt.file_category != fc:
                    if not dry_run:
                        dt.file_category = fc
                        dt.save()
                    updated += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'  ✓ {type_name} -> {fc.code}: {fc.name}'
                    ))
                else:
                    self.stdout.write(f'  {type_name} bereits verknüpft mit {fc.code}')
            else:
                if not dry_run:
                    dt = DocumentType.objects.create(
                        name=type_name,
                        description=description,
                        file_category=fc
                    )
                created += 1
                self.stdout.write(self.style.SUCCESS(
                    f'  + {type_name} erstellt -> {fc.code}: {fc.name}'
                ))

        self.stdout.write('')
        self.stdout.write(f'DocumentTypes aktualisiert: {updated}')
        self.stdout.write(f'DocumentTypes erstellt: {created}')
        
        if errors:
            self.stdout.write('')
            self.stdout.write(self.style.ERROR('Fehler:'))
            for error in errors:
                self.stdout.write(self.style.ERROR(f'  ! {error}'))

        if file_existing:
            self.stdout.write('')
            self.stdout.write(self.style.MIGRATE_HEADING('Bestehende Dokumente in Personalakten ablegen...\n'))
            
            filed_count = 0
            docs = Document.objects.filter(
                document_type__isnull=False,
                employee__isnull=False,
                document_type__file_category__isnull=False
            ).select_related('document_type', 'document_type__file_category', 'employee')
            
            for doc in docs:
                pf = getattr(doc.employee, 'personnel_file', None)
                if not pf:
                    continue
                
                exists = PersonnelFileEntry.objects.filter(
                    personnel_file=pf,
                    document=doc
                ).exists()
                
                if not exists:
                    if not dry_run:
                        PersonnelFileEntry.objects.create(
                            personnel_file=pf,
                            document=doc,
                            category=doc.document_type.file_category,
                            notes=f'Automatisch abgelegt aus {doc.document_type.name}'
                        )
                    filed_count += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'  ✓ {doc.original_filename[:50]} -> {pf.file_number}'
                    ))
            
            self.stdout.write('')
            self.stdout.write(f'Dokumente in Personalakten abgelegt: {filed_count}')

        self.stdout.write('')
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN abgeschlossen - keine Änderungen vorgenommen'))
        else:
            self.stdout.write(self.style.SUCCESS('Fertig!'))
