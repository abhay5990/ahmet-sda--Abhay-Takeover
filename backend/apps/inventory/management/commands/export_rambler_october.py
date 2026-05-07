"""Export login/pass/email/email_password for GameBoost October 2025 sales with rambler.ru email.

Usage:
    python manage.py export_rambler_october
    python manage.py export_rambler_october --output /tmp/rambler_oct.txt
"""

from pathlib import Path
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.inventory.models import OwnedProduct


class Command(BaseCommand):
    help = 'Export rambler.ru accounts sold on GameBoost in October 2025'

    def add_arguments(self, parser):
        parser.add_argument('--output', '-o', default='')

    def handle(self, *args, **options):
        output_path = options['output']
        if not output_path:
            from django.conf import settings
            output_path = str(settings.ROOT_DIR / 'tmp' / 'rambler_gameboost_october.txt')

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        qs = OwnedProduct.objects.filter(
            email__iendswith='rambler.ru',
            orders__integration_account__provider='gameboost',
            orders__sold_at__year=2026,
            orders__sold_at__month=2,
        ).distinct()

        total = qs.count()
        self.stdout.write(f'Found {total} accounts...')

        qs = qs.select_related('game')

        lines = []
        for op in qs.iterator(chunk_size=200):
            email = op.email or ''
            email_pass = op.email_password or ''

            secret = ''
            try:
                secret = op.raw_data.get('emailLoginData', {}).get('newSecretAnswer', '') or ''
            except Exception:
                pass

            game = op.game.name if op.game_id else ''

            parts = [email, email_pass]
            parts.append(secret)
            parts.append(game)

            lines.append(':'.join(parts))

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        self.stdout.write(self.style.SUCCESS(
            f'Done. {len(lines)} records written → {output_path}'
        ))
