"""Export email:email_password pairs from successful GameBoost sales after Sept 2025.

Successful statuses: delivered, completed, in_delivery
Date filter: sold_at >= 2025-09-01

Usage:
    python manage.py export_gameboost_email_pairs
    python manage.py export_gameboost_email_pairs --output /tmp/pairs.txt
    python manage.py export_gameboost_email_pairs --game "Brawl Stars"
"""

from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.inventory.models import OwnedProduct


_SUCCESSFUL_STATUSES = {'delivered', 'completed', 'in_delivery'}
_SINCE = datetime(2025, 9, 1, tzinfo=timezone.utc)


class Command(BaseCommand):
    help = 'Export email:email_password pairs from successful GameBoost sales (post Sept 2025)'

    def add_arguments(self, parser):
        parser.add_argument('--output', '-o', default='')
        parser.add_argument('--game', default='', help='Filter by game name (optional)')

    def handle(self, *args, **options):
        output_path = options['output']
        game_filter = options['game'].strip()

        if not output_path:
            from django.conf import settings
            from django.utils import timezone as dj_tz
            date_str = dj_tz.now().strftime('%Y-%m-%d_%H%M')
            suffix = f'_{game_filter.lower().replace(" ", "_")}' if game_filter else ''
            output_path = str(
                settings.ROOT_DIR / 'tmp' / f'gameboost_email_pairs{suffix}_{date_str}.txt'
            )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # OwnedProduct'ları GameBoost başarılı orderları üzerinden filtrele
        qs = OwnedProduct.objects.filter(
            orders__integration_account__provider='gameboost',
            orders__status__in=_SUCCESSFUL_STATUSES,
            orders__sold_at__gte=_SINCE,
        ).exclude(email='').distinct()

        if game_filter:
            qs = qs.filter(game__name__iexact=game_filter)

        total = qs.count()
        self.stdout.write(f'Found {total} accounts, reading email pairs...')

        pairs = []
        skipped_no_email_pass = 0

        for op in qs.iterator(chunk_size=500):
            email = op.email or ''
            email_password = op.email_password or ''

            if not email:
                skipped_no_email_pass += 1
                continue

            clean_pass = email_password.split(':')[0] if email_password else ''
            pairs.append(f'{email}:{clean_pass}' if clean_pass else email)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(pairs))

        self.stdout.write(self.style.SUCCESS(
            f'Done. {len(pairs)} pairs written'
            + (f', {skipped_no_email_pass} skipped (no email)' if skipped_no_email_pass else '')
            + f'\nOutput: {output_path}'
        ))
