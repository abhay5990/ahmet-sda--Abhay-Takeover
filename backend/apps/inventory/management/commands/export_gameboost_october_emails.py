"""Export email:email_password for all GameBoost October 2025 sales.

Usage:
    python manage.py export_gameboost_october_emails
"""

from pathlib import Path
from django.core.management.base import BaseCommand
from apps.inventory.models import OwnedProduct


class Command(BaseCommand):
    help = 'Export email:email_password for GameBoost October 2025 sales'

    def add_arguments(self, parser):
        parser.add_argument('--output', '-o', default='')

    def handle(self, *args, **options):
        output_path = options['output']
        if not output_path:
            from django.conf import settings
            output_path = str(settings.ROOT_DIR / 'tmp' / 'gameboost_october_emails.txt')

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        qs = OwnedProduct.objects.filter(
            orders__integration_account__provider='gameboost',
            orders__sold_at__year=2025,
            orders__sold_at__month=9,
        ).exclude(email='').distinct()

        total = qs.count()
        self.stdout.write(f'Found {total} accounts...')

        lines = []
        for op in qs.iterator(chunk_size=200):
            lines.append(f"{op.email}:{op.email_password or ''}")

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        self.stdout.write(self.style.SUCCESS(
            f'Done. {len(lines)} records → {output_path}'
        ))
