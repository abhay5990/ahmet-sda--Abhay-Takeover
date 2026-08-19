"""Safely renew PlayerAuctions offers before their recorded marketplace expiry.

The command fails closed: a listing is renewed only when it is locally active,
has no order or confirmed sale evidence, and the current remote offer is proven
active through PlayerAuctions before the existing relist service is invoked.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.integrations.providers import registry
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing
from apps.orders.models import Order
from apps.posting.models import OfferPoolActiveOffer, OfferPoolActiveOfferStatus, PoolSaleEvent
from apps.posting.services.relist import relist_listing


DEFAULT_RENEWAL_LEAD_HOURS = 72
_PA_ACTIVE_STATE = 1


def _remote_payload(result):
    data = getattr(result, 'data', None)
    if not isinstance(data, dict):
        return {}
    nested = data.get('data') or data.get('offer') or data.get('result')
    return nested if isinstance(nested, dict) else data


def _remote_offer_is_active(result) -> bool:
    """Accept only a successful PA offer-detail response with active state 1."""
    if not result or not getattr(result, 'ok', False):
        return False
    state = _remote_payload(result).get('state')
    try:
        return int(state) == _PA_ACTIVE_STATE
    except (TypeError, ValueError):
        return False


def _has_sale_or_open_order(listing: Listing) -> bool:
    """Never renew a listing that has local sale evidence or an active checkout."""
    if PoolSaleEvent.objects.filter(listing=listing).exists():
        return True
    if OfferPoolActiveOffer.objects.filter(
        listing=listing,
        status=OfferPoolActiveOfferStatus.SOLD,
    ).exists():
        return True
    return Order.objects.filter(
        integration_account=listing.integration_account,
        store_listing_id=listing.store_listing_id,
    ).exists()


def _remote_offer_is_verified_active(listing: Listing) -> bool:
    store = listing.integration_account
    if not store or not store.credential:
        return False
    try:
        client = registry.get_or_build_client('playerauctions', store.credential)
        return _remote_offer_is_active(client.get_offer_details(listing.store_listing_id))
    except Exception:
        return False


class Command(BaseCommand):
    help = 'Renew safely verified PlayerAuctions offers before marketplace expiry.'

    def add_arguments(self, parser):
        parser.add_argument('--execute', action='store_true')
        parser.add_argument(
            '--lead-hours',
            type=int,
            default=DEFAULT_RENEWAL_LEAD_HOURS,
            help='Renew listings expiring within this many hours (default: 72).',
        )

    def handle(self, *args, **options):
        execute = options['execute']
        lead_hours = max(1, options['lead_hours'])
        cutoff = timezone.now() + timedelta(hours=lead_hours)
        candidates = list(
            Listing.objects.filter(
                integration_account__provider='playerauctions',
                status=ListingStatus.LISTED,
                marketplace_expires_at__isnull=False,
                marketplace_expires_at__lte=cutoff,
            ).select_related('integration_account__credential').order_by('marketplace_expires_at')
        )
        stats = {'candidates': len(candidates), 'renewed': 0, 'skipped': 0, 'failed': 0}

        for listing in candidates:
            if _has_sale_or_open_order(listing):
                stats['skipped'] += 1
                self.stdout.write(f'SKIP {listing.store_listing_id}: sale or order evidence exists')
                continue
            if not execute:
                self.stdout.write(
                    f'READY {listing.store_listing_id}: expires '
                    f'{listing.marketplace_expires_at.isoformat()}'
                )
                continue
            if not _remote_offer_is_verified_active(listing):
                stats['skipped'] += 1
                self.stdout.write(f'SKIP {listing.store_listing_id}: remote offer not verified active')
                continue
            result = relist_listing(listing)
            if result.ok:
                stats['renewed'] += 1
                self.stdout.write(self.style.SUCCESS(
                    f'RENEWED {listing.store_listing_id} -> {result.new_listing.store_listing_id}'
                ))
            else:
                stats['failed'] += 1
                self.stdout.write(self.style.ERROR(
                    f'FAILED {listing.store_listing_id}: {result.error}'
                ))

        self.stdout.write(
            f"{'EXECUTED' if execute else 'DRY RUN'}: "
            f"candidates={stats['candidates']} renewed={stats['renewed']} "
            f"skipped={stats['skipped']} failed={stats['failed']}"
        )
