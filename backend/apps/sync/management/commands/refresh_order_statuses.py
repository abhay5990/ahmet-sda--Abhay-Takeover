"""Manually trigger order status refresh.

Usage:
    python manage.py refresh_order_statuses
"""

from django.core.management.base import BaseCommand

from apps.sync.services.order_status_refresh import run_order_status_refresh


class Command(BaseCommand):
    help = 'Refresh non-final order statuses (Eldorado delivered→completed, Gameboost pending→completed)'

    def handle(self, *args, **options):
        self.stdout.write('Starting order status refresh...')
        run_order_status_refresh()
        self.stdout.write(self.style.SUCCESS('Done.'))
