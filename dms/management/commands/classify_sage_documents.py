from django.core.management.base import BaseCommand
from dms.models import Document
from dms.tasks import classify_sage_document, get_or_create_document_type


class Command(BaseCommand):
    help = 'Klassifiziert Sage-Dokumente ohne DocumentType anhand des Dateinamens'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Zeigt nur was passieren würde, ohne Änderungen',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Alle Sage-Dokumente neu klassifizieren (auch bereits klassifizierte)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        process_all = options['all']
        
        documents = Document.objects.filter(source='SAGE').select_related('tenant', 'document_type')
        
        if not process_all:
            documents = documents.filter(document_type__isnull=True)
        
        self.stdout.write(f"Gefundene Sage-Dokumente: {documents.count()}")
        
        classified_count = 0
        unknown_count = 0
        already_set = 0
        
        for doc in documents:
            doc_type, is_personnel, category, description = classify_sage_document(doc.original_filename)
            
            if doc_type == 'UNBEKANNT':
                unknown_count += 1
                if options['verbosity'] >= 2:
                    self.stdout.write(f"  Unbekannt: {doc.original_filename}")
                continue
            
            if doc.document_type and not process_all:
                already_set += 1
                continue
            
            if dry_run:
                self.stdout.write(f"  Würde klassifizieren: {doc.original_filename} -> {doc_type} (Kategorie: {category})")
                classified_count += 1
            else:
                try:
                    document_type_obj = get_or_create_document_type(
                        doc_type, description, category, doc.tenant
                    )
                    doc.document_type = document_type_obj
                    doc.save(update_fields=['document_type'])
                    classified_count += 1
                    if options['verbosity'] >= 2:
                        self.stdout.write(self.style.SUCCESS(f"  Klassifiziert: {doc.original_filename} -> {doc_type}"))
                except Exception as e:
                    self.stderr.write(f"  Fehler bei {doc.original_filename}: {e}")
        
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Klassifiziert: {classified_count}"))
        self.stdout.write(f"Unbekannt: {unknown_count}")
        if already_set:
            self.stdout.write(f"Bereits gesetzt: {already_set}")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN - keine Änderungen durchgeführt"))
        else:
            self.stdout.write("")
            self.stdout.write("Tipp: Führen Sie jetzt 'python manage.py auto_file_documents' aus,")
            self.stdout.write("um die klassifizierten Dokumente in Personalakten abzulegen.")
