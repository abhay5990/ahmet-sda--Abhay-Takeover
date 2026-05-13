"""Import existing ref keys from a JSON export file.

Matches by source_product_id (LZT item_id) and sets ref_key on OwnedProduct.
Skips records that already have a ref_key or where no matching OwnedProduct exists.

Expected JSON format:
{
  "mappings": {
    "102079129": {
      "key_value": "#EHC2454",
      "item_id": 102079129,
      "created_at": "2025-09-25T19:15:22.351448"
    },
    ...
  }
}

Usage:
    python manage.py import_ref_keys path/to/account_keys.json
    python manage.py import_ref_keys path/to/account_keys.json --dry-run
    python manage.py import_ref_keys path/to/account_keys.json --overwrite
"""

import json

from django.core.management.base import BaseCommand

from apps.inventory.models import OwnedProduct


class Command(BaseCommand):
    help = 'Import ref keys from JSON export into OwnedProduct.ref_key'

    def add_arguments(self, parser):
        parser.add_argument(
            'json_file',
            type=str,
            help='Path to the JSON export file containing ref key mappings',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without writing to DB',
        )
        parser.add_argument(
            '--overwrite',
            action='store_true',
            help='Overwrite existing ref_key values',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            help='Batch size for bulk_update (default: 500)',
        )

    def handle(self, *args, **options):
        json_file = options['json_file']
        dry_run = options['dry_run']
        overwrite = options['overwrite']
        batch_size = options['batch_size']

        with open(json_file) as f:
            data = json.load(f)

        mappings = data.get('mappings', {})
        total = len(mappings)
        self.stdout.write(f'Loaded {total} ref key mappings from {json_file}')

        # Build item_id -> key_value lookup
        key_map: dict[int, str] = {}
        for entry in mappings.values():
            item_id = entry.get('item_id')
            key_value = entry.get('key_value', '')
            if item_id and key_value:
                key_map[int(item_id)] = key_value

        self.stdout.write(f'Valid mappings: {len(key_map)}')

        # Find matching OwnedProducts by source_product_id
        qs = OwnedProduct.objects.filter(
            source_product_id__in=list(key_map.keys()),
        )
        if not overwrite:
            qs = qs.filter(ref_key='')

        matched = 0
        skipped = 0
        to_update: list[OwnedProduct] = []

        for op in qs.iterator(chunk_size=batch_size):
            ref = key_map.get(op.source_product_id)
            if not ref:
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(
                    f'  OwnedProduct #{op.pk} (item_id={op.source_product_id}) '
                    f'-> {ref}'
                )
                matched += 1
                continue

            op.ref_key = ref
            to_update.append(op)

            if len(to_update) >= batch_size:
                OwnedProduct.objects.bulk_update(to_update, ['ref_key'])
                matched += len(to_update)
                self.stdout.write(f'  ... {matched} updated')
                to_update = []

        if to_update:
            OwnedProduct.objects.bulk_update(to_update, ['ref_key'])
            matched += len(to_update)

        prefix = '[DRY-RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Done: {matched} ref keys imported, {skipped} skipped.'
        ))
