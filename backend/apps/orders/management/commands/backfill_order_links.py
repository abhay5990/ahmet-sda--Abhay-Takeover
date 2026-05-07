"""Backfill listing and dropship_product FK on existing orders.

Looks up Listing by (integration_account, store_listing_id) and sets:
  - order.listing
  - order.dropship_product (from listing.dropship_product if present)

Orders that already have listing set are skipped (unless --overwrite).

Usage:
    python manage.py backfill_order_links
    python manage.py backfill_order_links --dry-run
    python manage.py backfill_order_links --marketplace eldorado
    python manage.py backfill_order_links --overwrite
"""
from django.core.management.base import BaseCommand

from apps.listings.models import Listing
from apps.orders.models import Order


class Command(BaseCommand):
    help = 'Backfill listing and dropship_product FK on existing orders'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without writing to DB',
        )
        parser.add_argument(
            '--marketplace',
            type=str,
            default='',
            help='Filter by marketplace provider (e.g. eldorado)',
        )
        parser.add_argument(
            '--overwrite',
            action='store_true',
            help='Re-link even if listing is already set',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            help='Batch size for bulk_update (default: 500)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        marketplace = options['marketplace']
        overwrite = options['overwrite']
        batch_size = options['batch_size']

        qs = Order.objects.filter(
            store_listing_id__gt='',
            integration_account__isnull=False,
        ).select_related('integration_account').order_by('id')

        if not overwrite:
            qs = qs.filter(listing__isnull=True)

        if marketplace:
            qs = qs.filter(integration_account__provider=marketplace)

        total = qs.count()
        self.stdout.write(f'Orders to process: {total}')

        # Pre-load listing lookup: (integration_account_id, store_listing_id) -> Listing
        listing_qs = Listing.objects.select_related('dropship_product').only(
            'id', 'integration_account_id', 'store_listing_id',
            'dropship_product_id',
        )
        listing_map: dict[tuple[int, str], Listing] = {}
        for lst in listing_qs.iterator(chunk_size=2000):
            key = (lst.integration_account_id, lst.store_listing_id)
            listing_map[key] = lst

        self.stdout.write(f'Listing lookup built: {len(listing_map)} entries')

        linked = 0
        not_found = 0
        to_update = []

        for order in qs.iterator(chunk_size=batch_size):
            key = (order.integration_account_id, order.store_listing_id)
            listing = listing_map.get(key)

            if not listing:
                not_found += 1
                continue

            if dry_run:
                dp_id = listing.dropship_product_id or '-'
                self.stdout.write(
                    f'  Order {order.store_order_id:20} -> '
                    f'Listing #{listing.pk}, DP={dp_id}'
                )
                linked += 1
                continue

            order.listing = listing
            if listing.dropship_product_id:
                order.dropship_product = listing.dropship_product
            to_update.append(order)

            if len(to_update) >= batch_size:
                Order.objects.bulk_update(
                    to_update, ['listing', 'dropship_product'],
                )
                linked += len(to_update)
                self.stdout.write(f'  ... {linked}/{total} linked')
                to_update = []

        if to_update:
            Order.objects.bulk_update(
                to_update, ['listing', 'dropship_product'],
            )
            linked += len(to_update)

        prefix = '[DRY-RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Done: {linked} linked, {not_found} listing not found.'
        ))
