"""
Management Command: fix_doctype_categories
============================================
Korrigiert die Zuordnung von Dokumententypen zu Aktenkategorien.

Basiert auf deutscher Lohnbuchhaltungs-Logik:
- 05.01: Gehaltsabrechnungen (Lohnscheine, Lohnkonto, Lohnjournal)
- 05.02: Lohnsteuer & Finanzamt (Lohnsteueranmeldung, ELStAM)
- 05.03: Sozialversicherung & Meldewesen (Beitragsnachweis, Meldebescheinigung)
- 05.04: Finanzbuchhaltung (FiBu-Journal, Buchungsstapel)
- 05.05: Altersvorsorge & ZVK
- 06.xx: Zeitwirtschaft & Fehlzeiten
- 07.xx: Gesundheit & Arbeitsschutz
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from dms.models import FileCategory, DocumentType, PersonnelFileEntry


CATEGORY_DEFINITIONS = {
    '05.01': {
        'name': 'Gehaltsabrechnungen',
        'description': 'Lohnscheine, Lohnkonto, Lohnjournal, Differenzabrechnungen',
        'retention_years': 10,
    },
    '05.02': {
        'name': 'Lohnsteuer & Finanzamt',
        'description': 'Lohnsteueranmeldung, Lohnsteuerbescheinigung, ELStAM',
        'retention_years': 10,
    },
    '05.03': {
        'name': 'Sozialversicherung & Meldewesen',
        'description': 'Beitragsnachweis, Meldebescheinigung (DEÜV), SV-Ausweis, Erstattungsanträge U1/U2',
        'retention_years': 10,
    },
    '05.04': {
        'name': 'Finanzbuchhaltung',
        'description': 'FiBu-Journal, Buchungsstapel, Sage-Export',
        'retention_years': 10,
    },
    '05.05': {
        'name': 'Altersvorsorge & ZVK',
        'description': 'ZVK-Beitragslisten, bAV-Verträge, Lohnkonto Altersvorsorge',
        'retention_years': 10,
    },
    '06.01': {
        'name': 'Arbeitszeitnachweise',
        'description': 'Stundenkalendarium, Zeitnachweise',
        'retention_years': 3,
    },
    '06.02': {
        'name': 'Urlaubsanträge',
        'description': 'Urlaubsanträge, Resturlaub',
        'retention_years': 3,
    },
    '06.03': {
        'name': 'Fehlzeiten & Kurzarbeit',
        'description': 'KUG, Saison-KUG, Überstunden',
        'retention_years': 3,
    },
    '07.01': {
        'name': 'Krankmeldungen',
        'description': 'AU-Bescheinigungen, Entgeltbescheinigung Kind krank',
        'retention_years': 3,
    },
    '07.05': {
        'name': 'Unfallmeldungen',
        'description': 'Berufsgenossenschaft, Unfallanzeigen',
        'retention_years': 30,
    },
    '03.04': {
        'name': 'Sozialversicherung',
        'description': 'SV-Meldungen, persönliche SV-Unterlagen',
        'retention_years': 30,
    },
}

DOCTYPE_CATEGORY_MAPPING = {
    'LOHNSCHEINE': '05.01',
    'KORREKTURLOHNSCHEINE': '05.01',
    'LOHNKONTO': '05.01',
    'JAHRESLOHNKONTO': '05.01',
    'ERWEITERTES LOHNKONTO': '05.01',
    'LOHNJOURNAL': '05.01',
    'JAHRESLOHNJOURNAL': '05.01',
    'DIFFERENZABRECHNUNG': '05.01',
    'STUNDENLOHNZETTEL': '05.01',
    'PFAENDUNG_BESCHLUSS': '05.01',
    
    'LOHNSTEUERANMELDUNG': '05.02',
    'LOHNSTEUERBESCHEINIGUNG': '05.02',
    'ELEKTRONISCHE LOHNSTEUERBESCHEINIGUNG': '05.02',
    'ELSTAM': '05.02',
    'ELSTAM - MELDEPROTOKOLL': '05.02',
    'ELSTAM-MELDUNG': '05.02',
    
    'BEITRAGSNACHWEIS': '05.03',
    'PROTOKOLL BEITRAGSNACHWEIS': '05.03',
    'BEITRAGSLISTE': '05.03',
    'BEITRAGSSCHULD': '05.03',
    'MELDEBESCHEINIGUNG': '05.03',
    'MELDEBESCHEINIGUNG (DEÜV)': '05.03',
    'SOZIALVERSICHERUNGSAUSWEIS': '05.03',
    'ERSTATTUNGSANTRAG': '05.03',
    'ERSTATTUNGSANTRAG U1/U2': '05.03',
    'ARBEITSBESCHEINIGUNG': '05.03',
    'A1_BESCHEINIGUNG': '05.03',
    'MINIJOB_BEFREIUNG': '05.03',
    
    'FIBU': '05.04',
    'FIBU-JOURNAL': '05.04',
    'FIBU-BUCHUNGSJOURNAL': '05.04',
    'BUCHUNGSSTAPEL': '05.04',
    'SAGE_EXPORT': '05.04',
    
    'ZVK': '05.05',
    'ZVK-LAK': '05.05',
    'ZVK-LAK-BEITRAGSLISTE': '05.05',
    'LOHNKONTO - ALTERSVORSORGE': '05.05',
    'BAV_VERTRAG': '05.05',
    
    'STUNDENKALENDARIUM': '06.01',
    'SOLL-ISTPROTOKOLL': '06.01',
    'RESTURLAUB': '06.02',
    
    'KUG': '06.03',
    'SAISON-KUG': '06.03',
    'SAISON-KUG ABRECHNUNGSLISTE': '06.03',
    
    'AU_BESCHEINIGUNG': '07.01',
    'ENTGELTBESCHEINIGUNG': '07.01',
    'ENTGELTBESCHEINIGUNG KIND KRANK': '07.01',
    
    'BERUFSGENOSSENSCHAFT': '07.05',
    'BERUFSGENOSSENSCHAFTSLISTE': '07.05',
    'JAHRESLOHNNACHWEIS BERUFSGENOSSENSCHAFT': '07.05',
    
    'DARLEHENSVERTRAG': '02.03',
    'DIENSTWAGEN_UEBERLASSUNG': '05.05',
}

STANDARD_DOCUMENT_TYPES = [
    {'name': 'ARBEITSBESCHEINIGUNG', 'category': '05.03', 'is_personnel': True},
    {'name': 'A1_BESCHEINIGUNG', 'category': '05.03', 'is_personnel': True},
    {'name': 'PFAENDUNG_BESCHLUSS', 'category': '05.01', 'is_personnel': True},
    {'name': 'DARLEHENSVERTRAG', 'category': '02.03', 'is_personnel': True},
    {'name': 'DIENSTWAGEN_UEBERLASSUNG', 'category': '05.05', 'is_personnel': True},
    {'name': 'MINIJOB_BEFREIUNG', 'category': '05.03', 'is_personnel': True},
    {'name': 'BEITRAGSLISTE', 'category': '05.03', 'is_personnel': False},
    {'name': 'BEITRAGSSCHULD', 'category': '05.03', 'is_personnel': False},
    {'name': 'BUCHUNGSSTAPEL', 'category': '05.04', 'is_personnel': False},
    {'name': 'SAGE_EXPORT', 'category': '05.04', 'is_personnel': False},
    {'name': 'BAV_VERTRAG', 'category': '05.05', 'is_personnel': True},
    {'name': 'STUNDENLOHNZETTEL', 'category': '05.01', 'is_personnel': True},
]


class Command(BaseCommand):
    help = 'Korrigiert Dokumenttyp-zu-Aktenkategorie-Zuordnungen'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Zeigt Änderungen ohne sie auszuführen',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        
        if dry_run:
            self.stdout.write(self.style.WARNING('=== DRY RUN - Keine Änderungen werden gespeichert ===\n'))
        
        with transaction.atomic():
            self.stdout.write(self.style.MIGRATE_HEADING('Phase 1: Kategorienamen aktualisieren'))
            self._update_category_names(dry_run)
            
            self.stdout.write(self.style.MIGRATE_HEADING('\nPhase 2: Dokumenttypen remappen'))
            self._remap_document_types(dry_run)
            
            self.stdout.write(self.style.MIGRATE_HEADING('\nPhase 3: Fehlende Standard-Dokumenttypen anlegen'))
            self._create_missing_document_types(dry_run)
            
            self.stdout.write(self.style.MIGRATE_HEADING('\nPhase 4: PersonnelFileEntries korrigieren'))
            self._fix_personnel_file_entries(dry_run)
            
            if dry_run:
                raise Exception("DRY RUN - Rollback")
        
        self.stdout.write(self.style.SUCCESS('\nAlle Korrekturen erfolgreich durchgeführt!'))

    def _update_category_names(self, dry_run):
        """Aktualisiert Kategorienamen auf korrekte deutsche Bezeichnungen"""
        for code, definition in CATEGORY_DEFINITIONS.items():
            try:
                category = FileCategory.objects.get(code=code)
                old_name = category.name
                if category.name != definition['name']:
                    self.stdout.write(
                        f"  {code}: '{old_name}' -> '{definition['name']}'"
                    )
                    if not dry_run:
                        category.name = definition['name']
                        category.description = definition.get('description', category.description)
                        category.save(update_fields=['name', 'description'])
            except FileCategory.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f"  {code}: Kategorie existiert nicht (wird beim filing plan erstellt)")
                )

    def _remap_document_types(self, dry_run):
        """Korrigiert falsche Kategorie-Zuordnungen"""
        updated_count = 0
        
        for doctype_name, target_category_code in DOCTYPE_CATEGORY_MAPPING.items():
            doctypes = DocumentType.objects.filter(name__iexact=doctype_name)
            
            if not doctypes.exists():
                continue
            
            try:
                target_category = FileCategory.objects.get(code=target_category_code)
            except FileCategory.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f"  SKIP {doctype_name}: Zielkategorie {target_category_code} existiert nicht")
                )
                continue
            
            for doctype in doctypes:
                current_cat = doctype.file_category.code if doctype.file_category else 'KEINE'
                
                if doctype.file_category != target_category:
                    old_cat_name = doctype.file_category.name if doctype.file_category else 'KEINE'
                    self.stdout.write(
                        f"  {doctype.name}: {current_cat} ({old_cat_name}) -> "
                        f"{target_category_code} ({target_category.name})"
                    )
                    if not dry_run:
                        doctype.file_category = target_category
                        doctype.save(update_fields=['file_category'])
                    updated_count += 1
        
        self.stdout.write(f"  -> {updated_count} Dokumenttypen aktualisiert")

    def _create_missing_document_types(self, dry_run):
        """Legt fehlende Standard-Dokumenttypen an"""
        created_count = 0
        
        for dt_config in STANDARD_DOCUMENT_TYPES:
            name = dt_config['name']
            
            if DocumentType.objects.filter(name__iexact=name).exists():
                continue
            
            try:
                category = FileCategory.objects.get(code=dt_config['category'])
            except FileCategory.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(f"  SKIP {name}: Kategorie {dt_config['category']} existiert nicht")
                )
                continue
            
            self.stdout.write(
                f"  NEU: {name} -> {dt_config['category']} ({category.name})"
            )
            
            if not dry_run:
                DocumentType.objects.create(
                    name=name,
                    description=f"Standard-Dokumenttyp: {name}",
                    file_category=category,
                    is_active=True,
                )
            created_count += 1
        
        self.stdout.write(f"  -> {created_count} Dokumenttypen angelegt")

    def _fix_personnel_file_entries(self, dry_run):
        """Korrigiert PersonnelFileEntry-Kategorien basierend auf DocumentType"""
        fixed_count = 0
        
        entries = PersonnelFileEntry.objects.select_related(
            'document__document_type__file_category',
            'category'
        ).exclude(document__document_type__isnull=True)
        
        for entry in entries:
            if not entry.document.document_type or not entry.document.document_type.file_category:
                continue
            
            correct_category = entry.document.document_type.file_category
            
            if entry.category != correct_category:
                old_cat = entry.category.code if entry.category else 'KEINE'
                self.stdout.write(
                    f"  Entry {entry.id}: {old_cat} -> {correct_category.code}"
                )
                if not dry_run:
                    entry.category = correct_category
                    entry.save(update_fields=['category'])
                fixed_count += 1
        
        self.stdout.write(f"  -> {fixed_count} Einträge korrigiert")
