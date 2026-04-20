"""Backfill our_fee on existing orders using FeeRule lookup.

Only percent fee is written, flat fee is excluded.
Orders that already have our_fee set are skipped.

Usage:
    python manage.py backfill_order_fees
    python manage.py backfill_order_fees --dry-run
    python manage.py backfill_order_fees --marketplace eldorado
    python manage.py backfill_order_fees --overwrite   # recalculate existing fees
"""
from django.core.management.base import BaseCommand

from apps.orders.enums import FeeType
from apps.orders.fees import calculate_fee, compute_fee_amount
from apps.orders.models import Order


class Command(BaseCommand):
    help = 'Backfill our_fee on existing orders using FeeRule (percent only, no flat fee)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Calculate but do not write to DB',
        )
        parser.add_argument(
            '--marketplace',
            type=str,
            default='',
            help='Filter by marketplace (e.g. eldorado, gameboost)',
        )
        parser.add_argument(
            '--overwrite',
            action='store_true',
            help='Recalculate even if our_fee is already set',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            help='Batch size (default: 500)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        marketplace = options['marketplace']
        overwrite = options['overwrite']
        batch_size = options['batch_size']

        qs = Order.objects.select_related(
            'integration_account', 'game',
        ).order_by('id')

        if not overwrite:
            qs = qs.filter(our_fee__isnull=True)

        if marketplace:
            qs = qs.filter(integration_account__provider=marketplace)

        total = qs.count()
        self.stdout.write(f'Orders to process: {total}')

        updated = 0
        skipped = 0
        no_rule = 0
        to_update = []

        for order in qs.iterator(chunk_size=batch_size):
            provider = ''
            if order.integration_account:
                provider = order.integration_account.provider

            if not provider:
                skipped += 1
                continue

            ref_date = order.sold_at.date() if order.sold_at else None

            rule = calculate_fee(
                marketplace=provider,
                fee_type=FeeType.SALE,
                product_category=order.product_category or '',
                game_id=order.game_id,
                ref_date=ref_date,
            )

            if not rule:
                no_rule += 1
                continue

            fee = compute_fee_amount(order.price, rule, include_flat=False)

            if dry_run:
                self.stdout.write(
                    f'  {order.store_order_id:20} | {provider:15} '
                    f'| {order.price:>10} | fee: {fee:>8} '
                    f'| rule: {rule.fee_percent}%'
                )
                updated += 1
                continue

            order.our_fee = fee
            to_update.append(order)

            if len(to_update) >= batch_size:
                Order.objects.bulk_update(to_update, ['our_fee'])
                updated += len(to_update)
                self.stdout.write(f'  ... {updated}/{total} updated')
                to_update = []

        # Remaining batch
        if to_update:
            Order.objects.bulk_update(to_update, ['our_fee'])
            updated += len(to_update)

        prefix = '[DRY-RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}Done: {updated} updated, '
            f'{skipped} skipped (no provider), '
            f'{no_rule} no matching rule.'
        ))
