"""Release pool dispatch reservations stuck in ACTIVE (abandoned by a dead worker).

A dispatch reserves pool items, runs a PostingJob, then finalizes or releases
them. If the worker process is killed mid-run (e.g. a deploy/restart), the
reservation stays ACTIVE and its items stay RESERVED forever — which blocks
removing the key and deleting the pool. This command returns those items to
PENDING and marks the reservation RELEASED.

Examples:
    # Release reservations older than the default 30 minutes
    python manage.py release_stale_pool_reservations

    # Preview only, no changes
    python manage.py release_stale_pool_reservations --dry-run

    # Force-release everything currently ACTIVE (use only when no dispatch is running)
    python manage.py release_stale_pool_reservations --minutes 0
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.posting.models import (
    OfferPoolItem,
    OfferPoolItemStatus,
    PoolDispatchReservation,
    PoolDispatchReservationStatus,
)
from apps.posting.services.pool.dispatcher import release_stale_reservations


class Command(BaseCommand):
    help = 'Release pool dispatch reservations stuck in ACTIVE past a max age.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--minutes',
            type=int,
            default=30,
            help='Release ACTIVE reservations older than this many minutes (default: 30).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be released without making changes.',
        )

    def handle(self, *args, **options):
        minutes = max(0, int(options['minutes']))
        max_age = timedelta(minutes=minutes)
        cutoff = timezone.now() - max_age

        stale = list(
            PoolDispatchReservation.objects.filter(
                status=PoolDispatchReservationStatus.ACTIVE,
                created_at__lt=cutoff,
            ).select_related('pool', 'store')
        )

        if not stale:
            self.stdout.write(self.style.SUCCESS(
                f'No ACTIVE reservations older than {minutes} minute(s).'
            ))
            return

        for res in stale:
            reserved = OfferPoolItem.objects.filter(
                reservation=res,
                status=OfferPoolItemStatus.RESERVED,
            ).count()
            self.stdout.write(
                f'  reservation #{res.pk} pool="{res.pool}" store="{res.store}" '
                f'created={res.created_at.isoformat()} reserved_items={reserved}'
            )

        if options['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'[dry-run] Would release {len(stale)} reservation(s). No changes made.'
            ))
            return

        released = release_stale_reservations(max_age=max_age)
        self.stdout.write(self.style.SUCCESS(
            f'Released {released} stale reservation(s); their items returned to PENDING.'
        ))
