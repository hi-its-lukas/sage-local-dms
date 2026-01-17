from django.core.management.base import BaseCommand
from django.db import transaction
from dms.models import Document, PersonnelFile, PersonnelFileEntry


class Command(BaseCommand):
    help = 'Legt alle Dokumente mit Mitarbeiter und Dokumenttyp automatisch in Personalakten ab'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Zeigt nur was passieren würde, ohne Änderungen',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        documents = Document.objects.filter(
            employee__isnull=False,
            document_type__isnull=False,
            document_type__file_category__isnull=False
        ).select_related('employee', 'document_type', 'document_type__file_category')
        
        self.stdout.write(f"Gefundene Dokumente mit Mitarbeiter und Kategorie: {documents.count()}")
        
        created_count = 0
        skipped_count = 0
        no_file_count = 0
        
        for doc in documents:
            try:
                personnel_file = doc.employee.personnel_file
            except PersonnelFile.DoesNotExist:
                no_file_count += 1
                if options['verbosity'] >= 2:
                    self.stdout.write(f"  Keine Personalakte für: {doc.employee}")
                continue
            
            existing = PersonnelFileEntry.objects.filter(
                personnel_file=personnel_file,
                document=doc
            ).exists()
            
            if existing:
                skipped_count += 1
                continue
            
            if dry_run:
                self.stdout.write(f"  Würde ablegen: {doc.title} -> {personnel_file.file_number} / {doc.document_type.file_category.name}")
                created_count += 1
            else:
                try:
                    with transaction.atomic():
                        PersonnelFileEntry.objects.create(
                            personnel_file=personnel_file,
                            document=doc,
                            category=doc.document_type.file_category,
                            notes=f"Automatisch abgelegt aus {doc.document_type.name}"
                        )
                        created_count += 1
                        if options['verbosity'] >= 2:
                            self.stdout.write(f"  Abgelegt: {doc.title}")
                except Exception as e:
                    self.stderr.write(f"  Fehler bei {doc.title}: {e}")
        
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Neu abgelegt: {created_count}"))
        self.stdout.write(f"Bereits vorhanden (übersprungen): {skipped_count}")
        self.stdout.write(f"Keine Personalakte: {no_file_count}")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN - keine Änderungen durchgeführt"))
