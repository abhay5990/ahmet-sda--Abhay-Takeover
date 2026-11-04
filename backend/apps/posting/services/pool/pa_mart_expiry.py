"""Return expired Mart PlayerAuctions pool clones to their pool (4 Nov 2026).

Why: PlayerAuctions account offers live 30 days. SDA's pre-expiry renewal is
disabled (``sync.renew_expiring_playerauctions``), so every Mart pool clone
eventually expires. The pool checker treats any SDA-active clone missing from
MCT's Official active-offer snapshot as "unknown" and skips the pool, so after
the first expiry a pool never refilled again. Live evidence on 4 Nov 2026:
300 SDA-active Mart clones, 3 live on PA, 297 expired; ~5,500 "Mart snapshot
did not confirm … skipping replenishment" warnings in 6 hours.

A missing ID alone is still not proof of anything (a partial cache could hide a
live offer), so this returns a clone to its pool ONLY when all of these hold:

* the snapshot is fresh (age proof within ``MAX_SNAPSHOT_AGE_SECONDS``);
* the clone's own provider expiry (``Listing.marketplace_expires_at``) passed
  more than ``EXPIRY_GRACE`` ago — an expired PA offer cannot be bought, and
  the grace covers late sale e-mails/orders for a purchase made just before
  expiry;
* every exact local sale/order/reservation/linkage guard passes.

Anything else keeps the old fail-closed behaviour. Only local SDA rows change
here; the normal guarded replenisher then recreates through the official Mart
route, up to the pool's target.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from apps.listings.enums import ListingStatus
from apps.listings.models import ListingOwnedProduct
from apps.orders.models import Order
from apps.posting.models import (
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    OfferPoolItem,
    OfferPoolItemStatus,
    PoolDispatchReservationStatus,
    PoolSaleEvent,
)

logger = logging.getLogger(__name__)

MART_ACCOUNT_SLUG = 'playerauctions-csgosmurfkings'
#: MCT refreshes its Official Mart snapshot every 15 minutes and itself refuses
#: anything older than 30 minutes.
MAX_SNAPSHOT_AGE_SECONDS = 1_200
#: An offer must have expired at least this long ago before it is returned.
EXPIRY_GRACE = datetime.timedelta(hours=2)
RETURN_MESSAGE = 'Expired on PlayerAuctions (absent from fresh Official snapshot) — returned to pool'


@dataclass
class ExpiryReturnResult:
    returned: list[str] = field(default_factory=list)
    #: Missing from the snapshot but not proven expired/safe: caller stays fail-closed.
    unresolved: dict[str, str] = field(default_factory=dict)


def snapshot_age_is_fresh(age_seconds) -> bool:
    try:
        return 0 <= float(age_seconds) <= MAX_SNAPSHOT_AGE_SECONDS
    except (TypeError, ValueError):
        return False


def expired_clone_block_reason(active_offer: OfferPoolActiveOffer, *, now=None) -> str | None:
    """Return why this missing clone must NOT be returned, or None when it is safe."""
    now = now or timezone.now()
    listing = active_offer.listing
    item = active_offer.pool_item
    if listing is None or item is None or active_offer.pool_offer_id is None:
        return 'missing_linkage'
    if listing.integration_account is None or listing.integration_account.slug != MART_ACCOUNT_SLUG:
        return 'not_mart'
    if listing.status != ListingStatus.LISTED:
        return 'listing_not_listed'
    if str(active_offer.store_listing_id) != str(listing.store_listing_id) or not str(active_offer.store_listing_id).isdigit():
        return 'offer_id_mismatch'
    expires_at = listing.marketplace_expires_at
    if expires_at is None:
        return 'no_expiry_recorded'
    if expires_at > now - EXPIRY_GRACE:
        return 'not_expired'
    if item.status != OfferPoolItemStatus.PUSHED:
        return f'item_{item.status}'
    if item.target_offer_id and item.target_offer_id != str(active_offer.store_listing_id):
        return 'item_target_mismatch'
    if Order.objects.filter(
        integration_account=listing.integration_account,
        store_listing_id=listing.store_listing_id,
    ).exists():
        return 'order_on_offer'
    if PoolSaleEvent.objects.filter(listing=listing).exists() or PoolSaleEvent.objects.filter(pool_item=item).exists():
        return 'sale_event'
    if OfferPoolActiveOffer.objects.filter(pool_item=item, status=OfferPoolActiveOfferStatus.SOLD).exists():
        return 'sold_clone'
    if item.owned_product_id and Order.objects.filter(owned_product_id=item.owned_product_id).exists():
        return 'order_on_product'
    if item.owned_product_id and OfferPoolItem.objects.filter(
        owned_product_id=item.owned_product_id,
        reservation__status=PoolDispatchReservationStatus.ACTIVE,
    ).exists():
        return 'active_reservation'
    return None


def _return_one(active_offer_id: int, *, now) -> str | None:
    """Locked re-check, then return the clone's credential to its pool."""
    with transaction.atomic():
        ao = (
            OfferPoolActiveOffer.objects.select_for_update()
            .select_related('listing', 'listing__integration_account', 'pool_item')
            .get(pk=active_offer_id)
        )
        if ao.status != OfferPoolActiveOfferStatus.ACTIVE:
            return 'no_longer_active'
        reason = expired_clone_block_reason(ao, now=now)
        if reason:
            return reason
        ao.status = OfferPoolActiveOfferStatus.FAILED
        ao.save(update_fields=['status', 'updated_at'])
        item = ao.pool_item
        item.status = OfferPoolItemStatus.PENDING
        item.pool_offer = None
        item.error_message = RETURN_MESSAGE
        item.target_offer_id = ''
        item.remote_credential_id = ''
        item.remote_state = 'absent'
        item.pushed_at = None
        item.save(update_fields=[
            'status', 'pool_offer', 'error_message', 'target_offer_id',
            'remote_credential_id', 'remote_state', 'pushed_at', 'updated_at',
        ])
        listing = ao.listing
        if listing.pk != getattr(ao.pool_offer, 'listing_id', None):
            listing.status = ListingStatus.CLOSED
            listing.removed_at = now
            listing.save(update_fields=['status', 'removed_at', 'updated_at'])
            ListingOwnedProduct.objects.filter(listing=listing).delete()
    return None


def return_expired_mart_clones(
    missing: list[OfferPoolActiveOffer],
    *,
    snapshot_age_seconds,
    now=None,
) -> ExpiryReturnResult:
    """Return each proven-expired, locally unsold missing clone to its pool."""
    now = now or timezone.now()
    result = ExpiryReturnResult()
    if not snapshot_age_is_fresh(snapshot_age_seconds):
        for active_offer in missing:
            result.unresolved[str(active_offer.store_listing_id)] = 'snapshot_not_fresh'
        return result
    for active_offer in missing:
        offer_id = str(active_offer.store_listing_id)
        reason = _return_one(active_offer.pk, now=now)
        if reason:
            result.unresolved[offer_id] = reason
        else:
            result.returned.append(offer_id)
    if result.returned:
        logger.info('pool_checker: returned %d expired Mart PA clone(s) to their pool: %s',
                    len(result.returned), ', '.join(result.returned[:20]))
    return result
