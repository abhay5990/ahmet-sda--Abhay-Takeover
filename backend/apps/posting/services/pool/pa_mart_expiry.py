"""Read-only diagnostics for missing expired Mart PlayerAuctions clones.

An active-only snapshot plus elapsed expiry is NOT proof that an account was
unsold. The current bridge supplies no complete sold/order coverage watermark,
no common sale/allocation ownership lease, and no lane-scoped return queue.
Consequently this release never recycles a key, closes a listing, or removes its
exact product linkage. The existing signed late-sale receiver keeps that linkage.
There is deliberately no environment switch that enables the unsafe transition.
A later, separately validated recovery contract is required before any return.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from django.utils import timezone

from apps.integrations.models import PaGmailOrderEvent
from apps.inventory.enums import OwnedProductStatus
from apps.listings.enums import ListingStatus
from apps.orders.models import Order
from apps.posting.models import (
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    OfferPoolItem,
    OfferPoolItemStatus,
    PoolDispatchReservationStatus,
    PoolSaleEvent,
)
from apps.posting.services.stock.pa_tracking import extract_tracking_code

MART_ACCOUNT_SLUG = 'playerauctions-csgosmurfkings'
MAX_SNAPSHOT_AGE_SECONDS = 1_200
EXPIRY_GRACE = datetime.timedelta(hours=2)
RECOVERY_HOLD_REASON = 'unsold_coverage_and_scoped_recovery_unverified'


@dataclass
class ExpiryReturnResult:
    returned: list[str] = field(default_factory=list)
    unresolved: dict[str, str] = field(default_factory=dict)


def snapshot_age_is_fresh(age_seconds: Any) -> bool:
    try:
        return not isinstance(age_seconds, bool) and 0 <= float(age_seconds) <= MAX_SNAPSHOT_AGE_SECONDS
    except (TypeError, ValueError, OverflowError):
        return False


def snapshot_is_complete(meta: Any) -> bool:
    """A page-one response must never prove absence when another page exists."""
    if not isinstance(meta, dict):
        return False
    pagination = meta.get('pagination')
    if not isinstance(pagination, dict):
        return False
    current, total = pagination.get('current_page'), pagination.get('total_pages')
    return type(current) is int and type(total) is int and current == total == 1


def expired_clone_block_reason(active_offer: OfferPoolActiveOffer, *, now=None) -> str:
    """Explain the hold using exact local facts; never attest that stock is unsold."""
    now = now or timezone.now()
    listing, item = active_offer.listing, active_offer.pool_item
    lane = active_offer.pool_offer
    if listing is None or item is None or lane is None:
        return 'missing_linkage'
    account = listing.integration_account
    if account is None or account.slug != MART_ACCOUNT_SLUG or account.provider != 'playerauctions':
        return 'not_mart'
    if active_offer.status != OfferPoolActiveOfferStatus.ACTIVE:
        return 'no_longer_active'
    if item.pool_id != active_offer.pool_id or lane.pool_id != active_offer.pool_id or item.pool_offer_id != lane.pk:
        return 'pool_lane_mismatch'
    if lane.listing.integration_account_id != listing.integration_account_id:
        return 'template_account_mismatch'
    if listing.status != ListingStatus.LISTED:
        return 'listing_not_listed'
    offer_id = str(active_offer.store_listing_id)
    if not offer_id.isdigit() or int(offer_id) <= 0 or offer_id != str(listing.store_listing_id):
        return 'offer_id_mismatch'
    if item.target_offer_id != offer_id:
        return 'item_target_mismatch'
    if item.status != OfferPoolItemStatus.PUSHED:
        return f'item_{item.status}'
    if not item.owned_product_id:
        return 'missing_owned_product'
    product_ids = list(listing.listing_owned_products.values_list('owned_product_id', flat=True))
    if product_ids != [item.owned_product_id]:
        return 'listing_product_mismatch'
    if Order.objects.filter(integration_account=account, store_listing_id=listing.store_listing_id).exists():
        return 'order_on_offer'
    if Order.objects.filter(owned_product_id=item.owned_product_id).exists():
        return 'order_on_product'
    if PoolSaleEvent.objects.filter(listing=listing).exists() or PoolSaleEvent.objects.filter(pool_item=item).exists():
        return 'sale_event'
    if OfferPoolActiveOffer.objects.filter(pool_item__owned_product_id=item.owned_product_id, status=OfferPoolActiveOfferStatus.SOLD).exists():
        return 'sold_clone'
    if item.owned_product.status not in {OwnedProductStatus.DRAFT, OwnedProductStatus.LISTED}:
        return 'product_sold_or_protected'
    if OfferPoolActiveOffer.objects.filter(pool_item__owned_product_id=item.owned_product_id, status=OfferPoolActiveOfferStatus.ACTIVE).exclude(pk=active_offer.pk).exists():
        return 'other_active_clone'
    if OfferPoolItem.objects.filter(owned_product_id=item.owned_product_id, reservation__status=PoolDispatchReservationStatus.ACTIVE).exists():
        return 'active_reservation'
    code = extract_tracking_code(listing.title)
    if PaGmailOrderEvent.objects.filter(listing=listing).exists() or (
        code and PaGmailOrderEvent.objects.filter(tracking_code=code).exists()
    ):
        return 'signed_order_event'
    expires_at = listing.marketplace_expires_at
    if expires_at is None:
        return 'no_expiry_recorded'
    if expires_at > now - EXPIRY_GRACE:
        return 'not_expired'
    # No grace interval or absence of local rows substitutes for remote unsold
    # coverage. This also avoids shared-pool reuse and races with late receipts.
    return RECOVERY_HOLD_REASON


def _return_one(active_offer_id: int, *, now) -> str:
    """Compatibility entry point is read-only too; direct callers cannot bypass the hold."""
    ao = OfferPoolActiveOffer.objects.select_related(
        'listing__integration_account', 'pool_item__owned_product', 'pool_offer__listing',
    ).get(pk=active_offer_id)
    return expired_clone_block_reason(ao, now=now)


def return_expired_mart_clones(
    missing: list[OfferPoolActiveOffer], *, snapshot_age_seconds, snapshot_meta=None, now=None,
) -> ExpiryReturnResult:
    """Report held candidates only. No database or marketplace write is performed."""
    now = now or timezone.now()
    result = ExpiryReturnResult()
    for active_offer in missing:
        offer_id = str(active_offer.store_listing_id)
        if not snapshot_age_is_fresh(snapshot_age_seconds):
            reason = 'snapshot_not_fresh'
        elif not snapshot_is_complete(snapshot_meta):
            reason = 'snapshot_incomplete'
        else:
            reason = _return_one(active_offer.pk, now=now)
        result.unresolved[offer_id] = reason
    return result
