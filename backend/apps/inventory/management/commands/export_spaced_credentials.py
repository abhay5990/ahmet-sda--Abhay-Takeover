"""Export OwnedProducts where login, password, email or email_password contains a space.

Usage:
    python manage.py export_spaced_credentials
    python manage.py export_spaced_credentials --output /tmp/spaced.json
    python manage.py export_spaced_credentials --field login password
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.inventory.models import OwnedProduct

_CHECKED_FIELDS = ['login', 'password', 'email', 'email_password']


class Command(BaseCommand):
    help = 'Export OwnedProducts whose credential fields contain spaces'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output', '-o',
            default='',
            help='Output file path (default: tmp/spaced_credentials_<date>.json)',
        )
        parser.add_argument(
            '--field',
            nargs='+',
            choices=_CHECKED_FIELDS,
            default=_CHECKED_FIELDS,
            dest='fields',
            help='Which fields to check for spaces (default: all four)',
        )

    def handle(self, *args, **options):
        output_path = options['output']
        fields_to_check = options['fields']

        if not output_path:
            from django.conf import settings
            date_str = timezone.now().strftime('%Y-%m-%d_%H%M')
            output_path = str(
                settings.ROOT_DIR / 'tmp' / f'spaced_credentials_{date_str}.json'
            )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # login ve email CharField olduğundan DB'de icontains yapılabilir,
        # ama password/email_password Fernet şifreli — hepsini Python'da kontrol ediyoruz.
        qs = OwnedProduct.objects.select_related('category', 'game').order_by('id')
        total = qs.count()
        self.stdout.write(f'Scanning {total} OwnedProduct records...')

        results = []
        for product in qs.iterator(chunk_size=500):
            matched_fields = {}
            for field in fields_to_check:
                value = getattr(product, field, '') or ''
                if ' ' in value:
                    matched_fields[field] = value

            if not matched_fields:
                continue

            entry = {
                'id': product.id,
                'category': product.category.title if product.category_id else None,
                'game': product.game.name if product.game_id else None,
                'status': product.status,
                'matched_fields': list(matched_fields.keys()),
            }
            for field in _CHECKED_FIELDS:
                entry[field] = getattr(product, field, '') or ''

            results.append(entry)

        output = {
            'exported_at': timezone.now().isoformat(),
            'checked_fields': fields_to_check,
            'total_scanned': total,
            'total_matched': len(results),
            'products': results,
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        self.stdout.write(self.style.SUCCESS(
            f'Done. {len(results)} product(s) with spaces found out of {total} scanned.\n'
            f'  Output: {output_path}'
        ))
