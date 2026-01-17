"""
Management Command: Sage Lohndokument-Typen erstellen

Erstellt alle Dokumenttypen und Matching-Regeln für Sage HR Lohndokumente.
Diese werden beim Import automatisch zugeordnet.

Verwendung:
    python manage.py create_sage_doctypes
    python manage.py create_sage_doctypes --tenant=00000001
"""

from django.core.management.base import BaseCommand
from dms.models import DocumentType, MatchingRule, Tenant


SAGE_DOCUMENT_TYPES = [
    {
        'name': 'Beitragsnachweis',
        'description': 'Beitragsnachweis für Sozialversicherung',
        'retention_days': 3650,
        'pattern': 'Beitragsnachweis',
    },
    {
        'name': 'Berechnung voraussichtliche Beitragsschuld',
        'description': 'Vorausberechnung der SV-Beiträge',
        'retention_days': 3650,
        'pattern': 'Berechnung voraussichtliche Beitragsschuld',
    },
    {
        'name': 'Berufsgenossenschaftsliste',
        'description': 'Liste für Berufsgenossenschaft',
        'retention_days': 3650,
        'pattern': 'Berufsgenossenschaftsliste',
    },
    {
        'name': 'Differenzabrechnung',
        'description': 'Korrekturabrechnung bei Lohndifferenzen',
        'retention_days': 3650,
        'pattern': 'Differenzabrechnung',
    },
    {
        'name': 'ELStAM - Meldeprotokoll',
        'description': 'Elektronische Lohnsteuerabzugsmerkmale Protokoll',
        'retention_days': 3650,
        'pattern': 'ELStAM',
    },
    {
        'name': 'Elektronische Lohnsteuerbescheinigung',
        'description': 'Jahresabschluss Lohnsteuerbescheinigung',
        'retention_days': 3650,
        'pattern': 'Elektronische Lohnsteuerbescheinigung',
    },
    {
        'name': 'Entgeltbescheinigung Kind krank',
        'description': 'Bescheinigung für Kinderkrankengeld',
        'retention_days': 3650,
        'pattern': 'Entgeltbescheinigung Kind krank',
    },
    {
        'name': 'Ereignis Protokoll - Nettolohnberechnung',
        'description': 'Protokoll der Nettolohnberechnung',
        'retention_days': 3650,
        'pattern': 'Ereignis Protokoll.*Nettolohnberechnung',
        'algorithm': 'REGEX',
    },
    {
        'name': 'Erstattungsantrag U1',
        'description': 'Antrag auf Erstattung nach AAG (Umlage 1)',
        'retention_days': 3650,
        'pattern': 'Erstattungsantrag U1',
    },
    {
        'name': 'Fibu-Buchungsjournal',
        'description': 'Buchungsjournal für Finanzbuchhaltung',
        'retention_days': 3650,
        'pattern': 'Fibu-Buchungsjournal',
    },
    {
        'name': 'Fibu-Journal',
        'description': 'Journal für Finanzbuchhaltung',
        'retention_days': 3650,
        'pattern': 'Fibu-Journal',
    },
    {
        'name': 'Jahreslohnjournal',
        'description': 'Jahresübersicht Lohnjournal',
        'retention_days': 3650,
        'pattern': 'Jahreslohnjournal',
    },
    {
        'name': 'Jahreslohnkonto',
        'description': 'Jahresübersicht Lohnkonto (kumuliert)',
        'retention_days': 3650,
        'pattern': 'Jahreslohnkonto',
    },
    {
        'name': 'Jahreslohnnachweis Berufsgenossenschaft',
        'description': 'Jahresmeldung für BG',
        'retention_days': 3650,
        'pattern': 'Jahreslohnnachweis Berufsgenossenschaft',
    },
    {
        'name': 'Korrekturlohnscheine',
        'description': 'Korrigierte Lohnscheine',
        'retention_days': 3650,
        'pattern': 'Korrekturlohnscheine',
    },
    {
        'name': 'Lohnjournal',
        'description': 'Monatliches Lohnjournal',
        'retention_days': 3650,
        'pattern': 'Lohnjournal',
    },
    {
        'name': 'Lohnkonto - Altersvorsorge',
        'description': 'Lohnkonto Übersicht Altersvorsorge',
        'retention_days': 3650,
        'pattern': 'Lohnkonto.*Altersvorsorge',
        'algorithm': 'REGEX',
    },
    {
        'name': 'Lohnkonto Bruttolohn',
        'description': 'Lohnkonto Bruttolohn Übersicht',
        'retention_days': 3650,
        'pattern': 'Lohnkonto Bruttolohn',
    },
    {
        'name': 'Lohnscheine',
        'description': 'Monatliche Lohn-/Gehaltsabrechnungen',
        'retention_days': 3650,
        'pattern': 'Lohnscheine',
    },
    {
        'name': 'Lohnsteueranmeldung',
        'description': 'Monatliche Lohnsteueranmeldung',
        'retention_days': 3650,
        'pattern': 'Lohnsteueranmeldung',
    },
    {
        'name': 'Meldebescheinigung',
        'description': 'SV-Meldebescheinigung',
        'retention_days': 3650,
        'pattern': 'Meldebescheinigung',
    },
    {
        'name': 'Protokoll Beitragsnachweis',
        'description': 'Protokoll zum Beitragsnachweis',
        'retention_days': 3650,
        'pattern': 'Protokoll Beitragsnachweis',
    },
    {
        'name': 'Protokoll LSt-Jahresausgleich',
        'description': 'Protokoll Lohnsteuer-Jahresausgleich',
        'retention_days': 3650,
        'pattern': 'Protokoll LSt-Jahresausgleich',
    },
    {
        'name': 'Resturlaub Vorjahr',
        'description': 'Übersicht Resturlaub aus Vorjahr',
        'retention_days': 1095,
        'pattern': 'Resturlaub Vorjahr',
    },
    {
        'name': 'Saison-KUG Antrag',
        'description': 'Antrag auf Saison-Kurzarbeitergeld',
        'retention_days': 3650,
        'pattern': 'Saison-KUG Antrag',
    },
    {
        'name': 'Saison-KUG Abrechnungsliste',
        'description': 'Abrechnungsliste Saison-Kurzarbeitergeld',
        'retention_days': 3650,
        'pattern': 'Saison-Kug Abrechnungsliste',
    },
    {
        'name': 'Soll-Istprotokoll',
        'description': 'Soll-Ist Vergleich Arbeitszeit',
        'retention_days': 1095,
        'pattern': 'Soll-Istprotokoll',
    },
    {
        'name': 'Stundenkalendarium',
        'description': 'Übersicht Arbeitsstunden pro Monat',
        'retention_days': 1095,
        'pattern': 'Stundenkalendarium',
    },
    {
        'name': 'ZVK-LAK-Beitragsliste',
        'description': 'Zusatzversorgungskasse / Lohnausgleichskasse Beitragsliste',
        'retention_days': 3650,
        'pattern': 'ZVK-LAK-Beitragsliste',
    },
    {
        'name': 'Erweitertes Lohnkonto',
        'description': 'Erweitertes Lohnkonto mit Details',
        'retention_days': 3650,
        'pattern': 'erweitertes Lohnkonto',
    },
    {
        'name': 'DATEV Buchungsstapel',
        'description': 'DATEV Export Buchungsstapel (CSV)',
        'retention_days': 3650,
        'pattern': 'EXTF_Buchungsstapel.*\\.CSV',
        'algorithm': 'REGEX',
    },
    {
        'name': 'Sage Export',
        'description': 'Sage Datenexport (CSV)',
        'retention_days': 3650,
        'pattern': 'E_Sage_.*\\.CSV',
        'algorithm': 'REGEX',
    },
]


class Command(BaseCommand):
    help = 'Erstellt Sage Lohndokument-Typen und Matching-Regeln'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            type=str,
            help='Mandanten-Code (z.B. 00000001). Wenn nicht angegeben, werden globale Typen erstellt.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Zeigt nur an was erstellt würde, ohne tatsächlich zu erstellen',
        )

    def handle(self, *args, **options):
        tenant = None
        tenant_code = options.get('tenant')
        dry_run = options.get('dry_run', False)
        
        if tenant_code:
            try:
                tenant = Tenant.objects.get(code=tenant_code)
                self.stdout.write(f"Erstelle Typen für Mandant: {tenant.name}")
            except Tenant.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"Mandant '{tenant_code}' nicht gefunden"))
                return

        created_types = 0
        created_rules = 0
        skipped = 0

        for doc_type_data in SAGE_DOCUMENT_TYPES:
            name = doc_type_data['name']
            description = doc_type_data.get('description', '')
            retention_days = doc_type_data.get('retention_days', 3650)
            pattern = doc_type_data.get('pattern', name)
            algorithm = doc_type_data.get('algorithm', 'EXACT')

            if dry_run:
                self.stdout.write(f"  [DRY-RUN] Würde erstellen: {name}")
                continue

            doc_type, type_created = DocumentType.objects.get_or_create(
                tenant=tenant,
                name=name,
                defaults={
                    'description': description,
                    'retention_days': retention_days,
                    'is_active': True,
                }
            )
            
            if type_created:
                created_types += 1
                self.stdout.write(self.style.SUCCESS(f"  + Dokumenttyp: {name}"))
            else:
                skipped += 1

            rule, rule_created = MatchingRule.objects.get_or_create(
                tenant=tenant,
                name=f"Auto: {name}",
                defaults={
                    'algorithm': algorithm,
                    'match_pattern': pattern,
                    'is_case_sensitive': False,
                    'is_active': True,
                    'priority': 10,
                    'assign_document_type': doc_type,
                }
            )

            if rule_created:
                created_rules += 1
                self.stdout.write(self.style.SUCCESS(f"    + Matching-Regel: {pattern}"))

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"\n[DRY-RUN] {len(SAGE_DOCUMENT_TYPES)} Typen würden erstellt werden"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\nFertig: {created_types} Dokumenttypen, {created_rules} Matching-Regeln erstellt, {skipped} übersprungen"
            ))
