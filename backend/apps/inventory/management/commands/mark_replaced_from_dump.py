"""Mark draft OwnedProducts as REPLACED when their login appears in a Gameboost order dump.

The dump file is a text export of Gameboost orders where credentials appear in
messages as lines like:
    Login: user@email.com          (plain)
    `Login: user@email.com         (code-block)
      Login: user@email.com        (indented)

Any line that contains "Login: <value>" (but not "Email Login:") is parsed.

Usage:
    # Dry-run (default) — shows what would change, writes nothing to DB
    python manage.py mark_replaced_from_dump --dump /path/to/dump.txt

    # Apply changes
    python manage.py mark_replaced_from_dump --dump /path/to/dump.txt --execute

    # Save JSON report
    python manage.py mark_replaced_from_dump --dump /path/to/dump.txt --execute --output /tmp/report.json
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.inventory.enums import OwnedProductStatus
from apps.inventory.models import OwnedProduct


class Command(BaseCommand):
    help = 'Mark draft OwnedProducts as REPLACED when their login appears anywhere in a Gameboost dump file'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dump', '-d',
            default='tmp/gameboost_full_dump.txt',
            help='Path to the Gameboost order dump file',
        )
        parser.add_argument(
            '--output', '-o',
            default='',
            help='Path for the JSON report (default: auto-generated in tmp/)',
        )
        parser.add_argument(
            '--execute',
            action='store_true',
            default=False,
            help='Apply changes (default is dry-run)',
        )

    def handle(self, *args, **options):
        dump_path = Path(options['dump'])
        execute = options['execute']
        output_path = options['output']

        if not dump_path.exists():
            raise CommandError(f'Dump file not found: {dump_path}')

        if not output_path:
            from django.conf import settings
            date_str = timezone.now().strftime('%Y-%m-%d_%H%M')
            output_path = str(
                Path(settings.BASE_DIR).parent / 'tmp' / f'mark_replaced_dump_{date_str}.json'
            )

        mode = 'EXECUTE' if execute else 'DRY-RUN'
        self.stdout.write(f'Mode: {mode}')
        self.stdout.write(f'Dump: {dump_path}')

        # 1. Load dump file as one big string for substring search
        self.stdout.write('Loading dump file...')
        dump_text = dump_path.read_text(encoding='utf-8', errors='replace')
        self.stdout.write(f'  Dump size: {len(dump_text):,} chars')

        # 2. Fetch all draft OwnedProducts
        self.stdout.write('Fetching draft OwnedProducts...')
        drafts = list(
            OwnedProduct.objects.filter(status=OwnedProductStatus.DRAFT)
            .select_related('category', 'game')
        )
        self.stdout.write(f'  Draft count: {len(drafts)}')

        # 3. Check each draft login against the dump (ctrl+f style)
        matched = []
        for p in drafts:
            if p.login and p.login in dump_text:
                matched.append(p)

        self.stdout.write(f'  Matched in dump: {len(matched)}')

        if not matched:
            self.stdout.write(self.style.WARNING('No matching draft records found. Nothing to do.'))
            self._write_report(output_path, mode, dump_path, [], {
                'draft_total': len(drafts),
                'draft_matched': 0,
                'replaced': 0,
            })
            return

        # 4. Print matches
        records = []
        for p in matched:
            record = {
                'id': p.id,
                'login': p.login,
                'category': p.category.title if p.category_id else None,
                'game': p.game.name if p.game_id else None,
                'status': p.status,
                'outcome': 'replaced',
            }
            records.append(record)
            self.stdout.write(f"  → id={p.id} {p.login!r} [{p.category.title if p.category_id else '?'}]")

        # 5. Apply or dry-run
        ids_to_update = [p.id for p in matched]

        if execute:
            with transaction.atomic():
                updated = OwnedProduct.objects.filter(id__in=ids_to_update).update(
                    status=OwnedProductStatus.REPLACED,
                )
            self.stdout.write(self.style.SUCCESS(f'Updated {updated} records → REPLACED'))
        else:
            self.stdout.write(self.style.NOTICE(
                f'[DRY-RUN] Would update {len(ids_to_update)} records → REPLACED'
            ))

        stats = {
            'draft_total': len(drafts),
            'draft_matched': len(matched),
            'replaced': len(ids_to_update) if execute else 0,
        }

        self._write_report(output_path, mode, dump_path, records, stats)

        self.stdout.write('\n── Summary ──────────────────────────────')
        self.stdout.write(f"  Draft total:      {stats['draft_total']}")
        self.stdout.write(f"  Matched in dump:  {stats['draft_matched']}")
        self.stdout.write(f"  Replaced:         {stats['replaced']}")
        self.stdout.write(f"  Report:           {output_path}")

    def _write_report(self, output_path, mode, dump_path, records, stats):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        report = {
            'mode': mode,
            'executed_at': timezone.now().isoformat(),
            'dump_file': str(dump_path),
            'stats': stats,
            'records': records,
        }
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
