"""Safely renew PlayerAuctions offers before their recorded marketplace expiry.

The official Mart lane queries and edits the *same* Account Offer with the
documented signed Offer API.  It never cancels/recreates an offer and never
starts a relay/browser session.  Other PA accounts retain the older relist
path until separately migrated.
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


DEFAULT_RENEWAL_LEAD_HOURS = 96
_PA_ACTIVE_STATE = 1


def _remote_payload(result):
    data = getattr(result, 'data', None)
    if hasattr(data, 'model_dump'):
        dumped = data.model_dump(by_alias=True)
        extra = dumped.pop('extra', {})
        return {
            **(extra if isinstance(extra, dict) else {}),
            **dumped,
        }
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


def _uses_official_offer_api_only(client) -> bool:
    marker = getattr(client, 'uses_official_offer_api_only', None)
    return bool(marker()) if callable(marker) else False


def _renew_official_mart_account_offer(listing: Listing, client) -> tuple[bool, str]:
    """Renew one Mart account offer in place after query/edit/re-query proof.

    Account-offer edits are replace-style requests.  The source is always the
    current signed remote query, not a partial local title/price patch.  The
    small HTML comment makes the renewal attributable and lets the re-query
    prove that the exact update reached the marketplace without changing buyer
    visible copy.
    """
    offer_id = str(listing.store_listing_id or '').strip()
    if not offer_id.isdigit():
        return False, 'listing has no numeric PlayerAuctions offer ID'
    try:
        detail = client.get_offer_details(offer_id, product_type='account')
    except Exception as exc:
        return False, f'official offer query failed: {exc}'
    if not _remote_offer_is_active(detail):
        return False, 'remote offer was not verified active'
    payload = _remote_payload(detail)
    if not payload:
        return False, 'official offer query returned no safe account payload'

    marker = f'<!--sda-renew:{offer_id}-{timezone.now().strftime("%Y%m%d%H%M%S")}-->'
    description = str(payload.get('offerDesc') or '')
    if len(description) + len(marker) > 3000:
        return False, 'official offer description has no room for the renewal marker'
    payload['offerDesc'] = f'{description}{marker}'
    payload['offerDuration'] = 30

    try:
        provider = registry.get_provider('playerauctions')
        updated = provider.update_listing(
            client,
            offer_id,
            {'payload': payload},
        )
    except Exception as exc:
        return False, f'official offer edit failed: {exc}'
    if not updated or not getattr(updated, 'ok', False):
        error = getattr(getattr(updated, 'error', None), 'message', None) or getattr(updated, 'error', None) or 'unknown official edit error'
        return False, f'official offer edit failed: {error}'

    try:
        verified = client.get_offer_details(offer_id, product_type='account')
    except Exception as exc:
        return False, f'official offer re-query failed: {exc}'
    verified_payload = _remote_payload(verified)
    if not (
        _remote_offer_is_active(verified)
        and int(verified_payload.get('offerDuration') or 0) == 30
        and marker in str(verified_payload.get('offerDesc') or '')
    ):
        return False, 'official offer renewal could not be re-verified'

    renewed_at = timezone.now()
    listing.listed_at = renewed_at
    listing.marketplace_expires_at = renewed_at + timedelta(days=30)
    listing.raw_data = {
        **(listing.raw_data or {}),
        'payload': payload,
        'official_renewal_marker': marker,
    }
    listing.save(update_fields=[
        'listed_at', 'marketplace_expires_at', 'raw_data', 'updated_at',
    ])
    return True, 'official account offer renewed and re-verified'


class Command(BaseCommand):
    help = 'Renew safely verified PlayerAuctions offers before marketplace expiry.'

    def add_arguments(self, parser):
        parser.add_argument('--execute', action='store_true')
        parser.add_argument(
            '--lead-hours',
            type=int,
            default=DEFAULT_RENEWAL_LEAD_HOURS,
            help='Renew listings expiring within this many hours (default: 96 / four days).',
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
            store = listing.integration_account
            client = None
            try:
                client = registry.get_or_build_client('playerauctions', store.credential)
            except Exception as exc:
                stats['failed'] += 1
                self.stdout.write(self.style.ERROR(
                    f'FAILED {listing.store_listing_id}: unable to build PlayerAuctions client: {exc}'
                ))
                continue
            if _uses_official_offer_api_only(client):
                renewed, message = _renew_official_mart_account_offer(listing, client)
                if renewed:
                    stats['renewed'] += 1
                    self.stdout.write(self.style.SUCCESS(
                        f'RENEWED {listing.store_listing_id}: {message}'
                    ))
                else:
                    stats['failed'] += 1
                    self.stdout.write(self.style.ERROR(
                        f'FAILED {listing.store_listing_id}: {message}'
                    ))
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
