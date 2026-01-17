from django.core.management.base import BaseCommand
from dms.models import FileCategory


class Command(BaseCommand):
    help = 'Erstellt den Standard-Aktenplan für Personalakten'

    def handle(self, *args, **options):
        categories = [
            {
                'code': '01',
                'name': 'Bewerbungsunterlagen',
                'description': 'Bewerbung, Lebenslauf, Zeugnisse vor Einstellung',
                'retention_years': 6,
                'retention_trigger': 'EXIT',
                'is_mandatory': False,
                'sort_order': 10,
            },
            {
                'code': '02',
                'name': 'Arbeitsvertrag',
                'description': 'Arbeitsvertrag, Änderungen, Zusatzvereinbarungen',
                'retention_years': 10,
                'retention_trigger': 'EXIT',
                'is_mandatory': True,
                'sort_order': 20,
                'children': [
                    {'code': '02.01', 'name': 'Arbeitsvertrag', 'retention_years': 10},
                    {'code': '02.02', 'name': 'Vertragsänderungen', 'retention_years': 10},
                    {'code': '02.03', 'name': 'Zusatzvereinbarungen', 'retention_years': 10},
                    {'code': '02.04', 'name': 'Befristungen', 'retention_years': 10},
                ]
            },
            {
                'code': '03',
                'name': 'Persönliche Daten',
                'description': 'Stammdaten, Bankverbindung, Steuer, SV',
                'retention_years': 6,
                'retention_trigger': 'EXIT',
                'is_mandatory': True,
                'sort_order': 30,
                'children': [
                    {'code': '03.01', 'name': 'Personalstammdaten', 'retention_years': 6},
                    {'code': '03.02', 'name': 'Bankverbindung', 'retention_years': 6},
                    {'code': '03.03', 'name': 'Steuerliche Unterlagen', 'retention_years': 6},
                    {'code': '03.04', 'name': 'Sozialversicherung', 'retention_years': 30},
                ]
            },
            {
                'code': '04',
                'name': 'Qualifikation & Entwicklung',
                'description': 'Zeugnisse, Zertifikate, Fortbildungen',
                'retention_years': 10,
                'retention_trigger': 'EXIT',
                'is_mandatory': False,
                'sort_order': 40,
                'children': [
                    {'code': '04.01', 'name': 'Schul-/Ausbildungszeugnisse', 'retention_years': 10},
                    {'code': '04.02', 'name': 'Fortbildungsnachweise', 'retention_years': 10},
                    {'code': '04.03', 'name': 'Zertifikate', 'retention_years': 10},
                    {'code': '04.04', 'name': 'Führerscheine & Fahrerlaubnisse', 'retention_years': 10},
                ]
            },
            {
                'code': '05',
                'name': 'Vergütung',
                'description': 'Gehaltsabrechnungen, Lohnsteuer, Sozialversicherung, FiBu',
                'retention_years': 10,
                'retention_trigger': 'DOCUMENT_DATE',
                'is_mandatory': True,
                'sort_order': 50,
                'children': [
                    {'code': '05.01', 'name': 'Gehaltsabrechnungen', 'retention_years': 10},
                    {'code': '05.02', 'name': 'Lohnsteuer & Finanzamt', 'retention_years': 10},
                    {'code': '05.03', 'name': 'Sozialversicherung & Meldewesen', 'retention_years': 10},
                    {'code': '05.04', 'name': 'Finanzbuchhaltung', 'retention_years': 10},
                    {'code': '05.05', 'name': 'Altersvorsorge & ZVK', 'retention_years': 10},
                ]
            },
            {
                'code': '06',
                'name': 'Arbeitszeit & Urlaub',
                'description': 'Arbeitszeitnachweise, Urlaubsanträge, Fehlzeiten',
                'retention_years': 3,
                'retention_trigger': 'DOCUMENT_DATE',
                'is_mandatory': False,
                'sort_order': 60,
                'children': [
                    {'code': '06.01', 'name': 'Arbeitszeitnachweise', 'retention_years': 3},
                    {'code': '06.02', 'name': 'Urlaubsanträge', 'retention_years': 3},
                    {'code': '06.03', 'name': 'Fehlzeiten & Kurzarbeit', 'retention_years': 3},
                    {'code': '06.04', 'name': 'Gleitzeitkonten', 'retention_years': 3},
                ]
            },
            {
                'code': '07',
                'name': 'Gesundheit & Arbeitsschutz',
                'description': 'AU-Bescheinigungen, Arbeitsmedizin, BEM',
                'retention_years': 3,
                'retention_trigger': 'DOCUMENT_DATE',
                'is_mandatory': False,
                'sort_order': 70,
                'children': [
                    {'code': '07.01', 'name': 'Krankmeldungen', 'retention_years': 3},
                    {'code': '07.02', 'name': 'AU-Bescheinigungen', 'retention_years': 3},
                    {'code': '07.03', 'name': 'Arbeitsmedizinische Vorsorge', 'retention_years': 10},
                    {'code': '07.04', 'name': 'BEM-Unterlagen', 'retention_years': 3},
                    {'code': '07.05', 'name': 'Unfallmeldungen', 'retention_years': 30},
                ]
            },
            {
                'code': '08',
                'name': 'Beurteilung & Feedback',
                'description': 'Beurteilungen, Zielvereinbarungen, Mitarbeitergespräche',
                'retention_years': 5,
                'retention_trigger': 'EXIT',
                'is_mandatory': False,
                'sort_order': 80,
                'children': [
                    {'code': '08.01', 'name': 'Leistungsbeurteilungen', 'retention_years': 5},
                    {'code': '08.02', 'name': 'Zielvereinbarungen', 'retention_years': 5},
                    {'code': '08.03', 'name': 'Mitarbeitergespräche', 'retention_years': 5},
                    {'code': '08.04', 'name': 'Feedback', 'retention_years': 5},
                ]
            },
            {
                'code': '09',
                'name': 'Disziplinarisches',
                'description': 'Abmahnungen, Ermahnungen, Verwarnungen',
                'retention_years': 3,
                'retention_trigger': 'DOCUMENT_DATE',
                'is_mandatory': False,
                'sort_order': 90,
                'children': [
                    {'code': '09.01', 'name': 'Abmahnungen', 'retention_years': 3},
                    {'code': '09.02', 'name': 'Ermahnungen', 'retention_years': 2},
                    {'code': '09.03', 'name': 'Verwarnungen', 'retention_years': 2},
                ]
            },
            {
                'code': '10',
                'name': 'Beendigung',
                'description': 'Kündigung, Aufhebungsvertrag, Zeugnis',
                'retention_years': 10,
                'retention_trigger': 'EXIT',
                'is_mandatory': False,
                'sort_order': 100,
                'children': [
                    {'code': '10.01', 'name': 'Kündigung', 'retention_years': 10},
                    {'code': '10.02', 'name': 'Aufhebungsvertrag', 'retention_years': 10},
                    {'code': '10.03', 'name': 'Arbeitszeugnis', 'retention_years': 10},
                    {'code': '10.04', 'name': 'Abschlussdokumente', 'retention_years': 10},
                ]
            },
            {
                'code': '99',
                'name': 'Sonstiges',
                'description': 'Nicht zugeordnete Dokumente',
                'retention_years': 10,
                'retention_trigger': 'EXIT',
                'is_mandatory': False,
                'sort_order': 999,
            },
        ]

        created_count = 0
        updated_count = 0

        for cat_data in categories:
            children = cat_data.pop('children', [])
            
            parent, created = FileCategory.objects.update_or_create(
                code=cat_data['code'],
                defaults=cat_data
            )
            
            if created:
                created_count += 1
                self.stdout.write(f"  + {parent.code} - {parent.name}")
            else:
                updated_count += 1
                self.stdout.write(f"  ~ {parent.code} - {parent.name}")
            
            for child_data in children:
                child_defaults = {
                    'name': child_data['name'],
                    'retention_years': child_data.get('retention_years', parent.retention_years),
                    'retention_trigger': child_data.get('retention_trigger', parent.retention_trigger),
                    'parent': parent,
                    'sort_order': parent.sort_order + int(child_data['code'].split('.')[1]),
                }
                
                child, child_created = FileCategory.objects.update_or_create(
                    code=child_data['code'],
                    defaults=child_defaults
                )
                
                if child_created:
                    created_count += 1
                    self.stdout.write(f"    + {child.code} - {child.name}")
                else:
                    updated_count += 1
                    self.stdout.write(f"    ~ {child.code} - {child.name}")

        self.stdout.write(self.style.SUCCESS(
            f'\nAktenplan erfolgreich angelegt: {created_count} neu, {updated_count} aktualisiert'
        ))
