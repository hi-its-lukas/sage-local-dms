"""
Management Command: Dokumente reklassifizieren

Wendet alle aktiven Matching-Regeln auf Dokumente an.
Kann alle Dokumente oder nur unklassifizierte verarbeiten.

Verwendung:
    python manage.py reclassify_documents                    # Nur unklassifizierte
    python manage.py reclassify_documents --all              # Alle Dokumente
    python manage.py reclassify_documents --tenant=00000001  # Nur ein Mandant
    python manage.py reclassify_documents --dry-run          # Vorschau ohne Änderungen
"""

import re
from django.core.management.base import BaseCommand
from django.db.models import Q
from dms.models import Document, MatchingRule, Tenant


class Command(BaseCommand):
    help = 'Reklassifiziert Dokumente anhand der Matching-Regeln'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Alle Dokumente verarbeiten, nicht nur unklassifizierte',
        )
        parser.add_argument(
            '--tenant',
            type=str,
            help='Nur Dokumente eines bestimmten Mandanten verarbeiten',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Zeigt nur an was geändert würde, ohne zu speichern',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Ausführliche Ausgabe',
        )

    def match_document(self, document, rule):
        """Prüft ob ein Dokument zur Regel passt"""
        search_text = f"{document.original_filename} {document.title}"
        pattern = rule.match_pattern
        
        if not rule.is_case_sensitive:
            search_text = search_text.lower()
            pattern = pattern.lower()

        if rule.algorithm == 'EXACT':
            return pattern in search_text
        elif rule.algorithm == 'ANY':
            words = pattern.split()
            return any(word in search_text for word in words)
        elif rule.algorithm == 'ALL':
            words = pattern.split()
            return all(word in search_text for word in words)
        elif rule.algorithm == 'REGEX':
            try:
                flags = 0 if rule.is_case_sensitive else re.IGNORECASE
                return bool(re.search(pattern, search_text, flags))
            except re.error:
                return False
        elif rule.algorithm == 'FUZZY':
            words = pattern.split()
            for word in words:
                if len(word) >= 4:
                    for i in range(len(search_text) - len(word) + 1):
                        substring = search_text[i:i+len(word)]
                        matches = sum(a == b for a, b in zip(word, substring))
                        if matches >= len(word) * 0.8:
                            return True
            return False
        
        return False

    def handle(self, *args, **options):
        process_all = options.get('all', False)
        tenant_code = options.get('tenant')
        dry_run = options.get('dry_run', False)
        verbose = options.get('verbose', False)

        tenant = None
        if tenant_code:
            try:
                tenant = Tenant.objects.get(code=tenant_code)
                self.stdout.write(f"Verarbeite Mandant: {tenant.name}")
            except Tenant.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"Mandant '{tenant_code}' nicht gefunden"))
                return

        documents = Document.objects.all()
        if tenant:
            documents = documents.filter(tenant=tenant)
        if not process_all:
            documents = documents.filter(document_type__isnull=True)

        rules = MatchingRule.objects.filter(is_active=True).order_by('-priority')
        if tenant:
            rules = rules.filter(Q(tenant=tenant) | Q(tenant__isnull=True))

        total = documents.count()
        matched = 0
        updated = 0

        self.stdout.write(f"Verarbeite {total} Dokumente mit {rules.count()} aktiven Regeln...")

        for doc in documents.iterator():
            for rule in rules:
                if self.match_document(doc, rule):
                    matched += 1
                    changes = []
                    
                    if rule.assign_document_type and doc.document_type != rule.assign_document_type:
                        changes.append(f"Typ: {rule.assign_document_type.name}")
                        if not dry_run:
                            doc.document_type = rule.assign_document_type

                    if rule.assign_employee and doc.employee != rule.assign_employee:
                        changes.append(f"Mitarbeiter: {rule.assign_employee}")
                        if not dry_run:
                            doc.employee = rule.assign_employee

                    if rule.assign_status and doc.status != rule.assign_status:
                        changes.append(f"Status: {rule.assign_status}")
                        if not dry_run:
                            doc.status = rule.assign_status

                    if changes:
                        updated += 1
                        if verbose or dry_run:
                            prefix = "[DRY-RUN] " if dry_run else ""
                            self.stdout.write(
                                f"  {prefix}{doc.original_filename}: {', '.join(changes)} (Regel: {rule.name})"
                            )
                        if not dry_run:
                            doc.save()

                    if rule.assign_tags.exists() and not dry_run:
                        doc.tags.add(*rule.assign_tags.all())

                    break

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"\n[DRY-RUN] {matched} Dokumente würden klassifiziert, {updated} geändert"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\nFertig: {matched} Dokumente klassifiziert, {updated} geändert"
            ))
