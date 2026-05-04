"""Pause listings that are approaching their marketplace expiry threshold.

Eldorado offers expire after ~21 days, PlayerAuctions after ~30 days.
This command marks LISTED listings as PAUSED in the DB once they exceed
the provider-specific threshold (no API calls).

Usage:
    python manage.py pause_expiring_listings              # dry-run
    python manage.py pause_expiring_listings --execute     # actually update DB
"""

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.listings.enums import ListingStatus
from apps.listings.models import Listing

logger = logging.getLogger(__name__)

# Provider → max listing age in days (hardcoded for now)
EXPIRY_THRESHOLDS: dict[str, int] = {
    'eldorado': 21,
    'playerauctions': 30,
}


class Command(BaseCommand):
    help = 'Pause listings approaching marketplace expiry (DB-only, no API calls).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--execute',
            action='store_true',
            help='Actually update DB. Without this flag, dry-run only.',
        )

    def handle(self, *args, **options):
        execute = options['execute']
        now = timezone.now()
        total_paused = 0

        for provider, days in EXPIRY_THRESHOLDS.items():
            cutoff = now - timedelta(days=days)

            qs = Listing.objects.filter(
                status=ListingStatus.LISTED,
                integration_account__provider=provider,
                listed_at__isnull=False,
                listed_at__lte=cutoff,
            ).select_related('integration_account')

            count = qs.count()
            if count == 0:
                self.stdout.write(f'  {provider}: no expiring listings (threshold={days}d)')
                continue

            if not execute:
                self.stdout.write(self.style.WARNING(
                    f'  {provider}: {count} listings older than {days}d (dry-run)'
                ))
                for listing in qs[:10]:
                    age = (now - listing.listed_at).days
                    self.stdout.write(
                        f'    {listing.store_listing_id} | '
                        f'age={age}d | {listing.title[:50]}'
                    )
                if count > 10:
                    self.stdout.write(f'    ... and {count - 10} more')
                continue

            updated = qs.update(status=ListingStatus.PAUSED)
            total_paused += updated
            logger.info('Paused %d expiring %s listings (threshold=%dd)', updated, provider, days)
            self.stdout.write(self.style.SUCCESS(
                f'  {provider}: paused {updated} listings (threshold={days}d)'
            ))

        if execute:
            self.stdout.write(self.style.SUCCESS(f'Done. Total paused: {total_paused}'))
        else:
            self.stdout.write(self.style.WARNING('DRY RUN — add --execute to apply changes.'))
