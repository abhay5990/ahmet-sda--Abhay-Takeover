"""Fix Gameboost delivered→completed + Eldorado delivered investigation.

Usage:
    # Dry run (default) — shows what would change
    python manage.py fix_order_statuses

    # Apply Gameboost fix
    python manage.py fix_order_statuses --apply

    # Only show Eldorado delivered orders
    python manage.py fix_order_statuses --eldorado-only
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.orders.enums import OrderStatus
from apps.orders.models import Order


class Command(BaseCommand):
    help = 'Fix Gameboost delivered→completed and investigate Eldorado delivered orders'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Actually apply the Gameboost fix (default is dry-run)',
        )
        parser.add_argument(
            '--eldorado-only',
            action='store_true',
            help='Only show Eldorado delivered investigation',
        )

    def handle(self, *args, **options):
        apply = options['apply']
        eldorado_only = options['eldorado_only']

        if not eldorado_only:
            self._fix_gameboost(apply)

        self.stdout.write('')
        self._investigate_eldorado()

    def _fix_gameboost(self, apply: bool):
        """Fix Gameboost orders: delivered → completed."""
        self.stdout.write(self.style.MIGRATE_HEADING(
            '=== Gameboost: delivered → completed ==='
        ))

        gb_delivered = Order.objects.filter(
            integration_account__provider='gameboost',
            status=OrderStatus.DELIVERED,
        )
        count = gb_delivered.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS(
                'No Gameboost orders with delivered status found.'
            ))
            return

        self.stdout.write(f'Found {count} Gameboost orders with status=delivered')

        if not apply:
            self.stdout.write(self.style.WARNING(
                'DRY RUN — use --apply to update these orders'
            ))
            # Show a sample
            sample = gb_delivered.order_by('-sold_at')[:5]
            for order in sample:
                self.stdout.write(
                    f'  Order #{order.store_order_id} | '
                    f'sold_at={order.sold_at} | '
                    f'price={order.price} {order.currency}'
                )
            if count > 5:
                self.stdout.write(f'  ... and {count - 5} more')
            return

        updated = gb_delivered.update(status=OrderStatus.COMPLETED)
        self.stdout.write(self.style.SUCCESS(
            f'Updated {updated} Gameboost orders: delivered → completed'
        ))

    def _investigate_eldorado(self):
        """Show Eldorado delivered orders for investigation."""
        self.stdout.write(self.style.MIGRATE_HEADING(
            '=== Eldorado: delivered orders investigation ==='
        ))

        eld_delivered = Order.objects.filter(
            integration_account__provider='eldorado',
            status=OrderStatus.DELIVERED,
        ).order_by('sold_at')

        count = eld_delivered.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS(
                'No Eldorado orders with delivered status found.'
            ))
            return

        self.stdout.write(f'Found {count} Eldorado orders with status=delivered')

        # Oldest and newest
        oldest = eld_delivered.first()
        newest = eld_delivered.order_by('-sold_at').first()
        self.stdout.write(f'  Oldest: #{oldest.store_order_id} | sold_at={oldest.sold_at}')
        self.stdout.write(f'  Newest: #{newest.store_order_id} | sold_at={newest.sold_at}')

        # Status distribution across all Eldorado orders
        self.stdout.write('')
        self.stdout.write('Eldorado order status distribution:')
        stats = (
            Order.objects
            .filter(integration_account__provider='eldorado')
            .values('status')
            .annotate(count=Count('id'))
            .order_by('status')
        )
        for row in stats:
            self.stdout.write(f'  {row["status"]}: {row["count"]}')

        # Show delivered orders (limited)
        self.stdout.write('')
        self.stdout.write('Eldorado delivered orders (oldest 20):')
        for order in eld_delivered[:20]:
            raw_state = ''
            if order.raw_data:
                state_obj = order.raw_data.get('state', {})
                if isinstance(state_obj, dict):
                    raw_state = state_obj.get('state', '')
            self.stdout.write(
                f'  #{order.store_order_id} | '
                f'sold_at={order.sold_at} | '
                f'price={order.price} {order.currency} | '
                f'raw_state={raw_state}'
            )
