from django.core.management.base import BaseCommand
from dms.models import Document


class Command(BaseCommand):
    help = 'Aktualisiert period_year und period_month für alle Dokumente basierend auf month_folder in metadata'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Zeigt nur an was geändert würde, ohne zu speichern',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Aktualisiert auch Dokumente die bereits eine Periode haben',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options.get('force', False)
        
        if force:
            docs = Document.objects.all()
        else:
            docs = Document.objects.filter(period_year__isnull=True)
        
        total = docs.count()
        updated = 0
        skipped = 0
        
        self.stdout.write(f"Prüfe {total} Dokumente...")
        
        for doc in docs.iterator():
            month_folder = doc.metadata.get('month_folder') if doc.metadata else None
            
            if not month_folder or len(month_folder) != 6:
                skipped += 1
                continue
            
            try:
                year = int(month_folder[:4])
                month = int(month_folder[4:6])
                
                if 1 <= month <= 12 and 2000 <= year <= 2100:
                    if dry_run:
                        self.stdout.write(f"  [DRY-RUN] {doc.title}: {month_folder} → {month:02d}/{year}")
                    else:
                        doc.period_year = year
                        doc.period_month = month
                        doc.save(update_fields=['period_year', 'period_month'])
                    
                    updated += 1
                else:
                    skipped += 1
            except (ValueError, TypeError):
                skipped += 1
        
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"\n[DRY-RUN] Würde {updated} Dokumente aktualisieren, {skipped} übersprungen"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\n{updated} Dokumente aktualisiert, {skipped} übersprungen (kein month_folder)"
            ))
