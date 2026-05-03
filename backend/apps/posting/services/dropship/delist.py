"""Dropship delist service — remove marketplace offers for DropshipProducts.

Used by:
- API views (manual delete from UI)
- Future: listings page bulk delist

Bulk strategy:
- PlayerAuctions: groups all listings per store into one cancel_offers() call.
- Gameboost / Eldorado / G2G: sequential, one API call per listing.

Only marks a DropshipProduct as DELETED when ALL its marketplace offers have
been successfully removed. If any offer removal fails, the DP stays LISTED so
the user can retry or the cleaner will pick it up.

Max bulk size: BULK_DELIST_LIMIT (50). Caller is responsible for enforcing
this before calling delist_bulk().
"""

from __future__ import annotations

import logging
from typing import NamedTuple

from django.utils import timezone

from apps.integrations.providers import registry
from apps.integrations.proxy_pool import build_proxy_pool
from apps.inventory.enums import DropshipProductStatus
from apps.inventory.models import DropshipProduct
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing
from apps.posting.models import PostingLog, PostingLogLevel

logger = logging.getLogger(__name__)

BULK_DELIST_LIMIT = 50


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class DelistResult(NamedTuple):
    ok: bool
    error: str = ''


class BulkDelistResult(NamedTuple):
    succeeded: list[int]     # DP IDs that were fully delisted + marked DELETED
    failed: list[int]        # DP IDs where at least one offer removal failed
    errors: dict[int, str]   # DP ID → human-readable error


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def delist_single(dp: DropshipProduct) -> DelistResult:
    """Remove all marketplace offers for one DropshipProduct.

    Only marks the DP as DELETED if all offers were successfully removed.
    Returns DelistResult(ok=True) on full success, DelistResult(ok=False, error=...)
    on any failure.
    """
    listings = list(
        Listing.objects.filter(
            dropship_product=dp,
            status=ListingStatus.LISTED,
        ).select_related('integration_account', 'integration_account__credential')
    )

    if not listings:
        # No active marketplace offers — safe to mark directly
        _mark_dp_deleted(dp)
        return DelistResult(ok=True)

    proxy_pool = build_proxy_pool()
    all_ok = True
    for listing in listings:
        if not _delete_one_listing(listing, proxy_pool=proxy_pool):
            all_ok = False

    if all_ok:
        _mark_dp_deleted(dp)
        return DelistResult(ok=True)

    return DelistResult(ok=False, error='Failed to remove some marketplace offers')


def delist_bulk(dps: list[DropshipProduct]) -> BulkDelistResult:
    """Remove marketplace offers for multiple DropshipProducts.

    Groups PlayerAuctions listings per store for a single bulk cancel call.
    All other marketplaces are processed sequentially.

    Args:
        dps: List of DropshipProduct instances to delist (max BULK_DELIST_LIMIT).

    Returns:
        BulkDelistResult with succeeded/failed DP ID lists and per-DP error messages.
    """
    if len(dps) > BULK_DELIST_LIMIT:
        dps = dps[:BULK_DELIST_LIMIT]

    dp_ids = [dp.id for dp in dps]

    # Fetch all LISTED listings for all DPs in a single query
    all_listings = list(
        Listing.objects.filter(
            dropship_product_id__in=dp_ids,
            status=ListingStatus.LISTED,
        ).select_related('integration_account', 'integration_account__credential')
    )

    # Partition: PA listings grouped by store, everything else sequential
    listings_by_dp: dict[int, list[Listing]] = {dp_id: [] for dp_id in dp_ids}
    pa_by_store: dict[int, list[Listing]] = {}   # store_id → [listing, ...]
    other_listings: list[Listing] = []

    for listing in all_listings:
        listings_by_dp[listing.dropship_product_id].append(listing)
        store = listing.integration_account
        if store and store.provider == 'playerauctions':
            pa_by_store.setdefault(store.id, []).append(listing)
        else:
            other_listings.append(listing)

    # Per-listing success tracker: listing.id → bool
    listing_ok: dict[int, bool] = {}
    proxy_pool = build_proxy_pool()

    # 1. PA bulk cancel (one call per store account)
    for store_listings in pa_by_store.values():
        _cancel_pa_bulk(store_listings, listing_ok, proxy_pool=proxy_pool)

    # 2. Other marketplaces: one by one
    for listing in other_listings:
        listing_ok[listing.id] = _delete_one_listing(listing, proxy_pool=proxy_pool)

    # 3. Evaluate per-DP result
    to_mark_deleted: list[int] = []
    succeeded: list[int] = []
    failed: list[int] = []
    errors: dict[int, str] = {}

    for dp_id in dp_ids:
        dp_listings = listings_by_dp[dp_id]

        if not dp_listings:
            # No active offers — safe to mark directly
            to_mark_deleted.append(dp_id)
            succeeded.append(dp_id)
            continue

        if all(listing_ok.get(l.id, False) for l in dp_listings):
            to_mark_deleted.append(dp_id)
            succeeded.append(dp_id)
        else:
            failed_stores = sorted({
                l.integration_account.name
                for l in dp_listings
                if not listing_ok.get(l.id, False) and l.integration_account
            })
            failed.append(dp_id)
            errors[dp_id] = f"Failed to remove offer(s) on: {', '.join(failed_stores) or 'unknown'}"

    # Batch-mark all succeeded DPs as DELETED in a single query
    if to_mark_deleted:
        _mark_dp_deleted_bulk(to_mark_deleted)

    return BulkDelistResult(succeeded=succeeded, failed=failed, errors=errors)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _mark_dp_deleted(dp: DropshipProduct) -> None:
    dp.status = DropshipProductStatus.DELETED
    dp.deleted_at = timezone.now()
    dp.save(update_fields=['status', 'deleted_at'])  # auto_now handles updated_at


def _mark_dp_deleted_bulk(dp_ids: list[int]) -> None:
    """Batch-mark multiple DropshipProducts as DELETED in a single query."""
    DropshipProduct.objects.filter(id__in=dp_ids).update(
        status=DropshipProductStatus.DELETED,
        deleted_at=timezone.now(),
        updated_at=timezone.now(),  # auto_now skipped by .update(), set explicitly
    )


def _cancel_pa_bulk(
    listings: list[Listing], results: dict[int, bool], *, proxy_pool=None,
) -> None:
    """Cancel multiple PlayerAuctions listings in a single API call.

    Updates results dict in-place: listing.id → True/False.
    On success also updates each listing to CLOSED in the DB.
    """
    from apis_sdk.clients.marketplaces.playerauctions.models import PlayerAuctionsCancelRequest

    store = listings[0].integration_account
    if not store or not store.credential:
        for lst in listings:
            results[lst.id] = False
        return

    try:
        facade = registry.get_or_build_client('playerauctions', store.credential, proxy_pool=proxy_pool)
        offer_ids = [int(lst.store_listing_id) for lst in listings]
        facade.cancel_offers(PlayerAuctionsCancelRequest(offerIds=offer_ids))

        # Success — mark all DELETED in a single query
        now = timezone.now()
        Listing.objects.filter(id__in=[lst.id for lst in listings]).update(
            status=ListingStatus.DELETED,
            removed_at=now,
        )
        for lst in listings:
            results[lst.id] = True

    except Exception as e:
        logger.warning(
            "PA bulk cancel failed for store '%s' (%d offers): %s",
            store.name, len(listings), e,
        )
        PostingLog.objects.create(
            task_name='dropship_cleaner',
            level=PostingLogLevel.ERROR,
            message=f"PA bulk cancel failed: {len(listings)} offers on {store.name}",
            detail={
                'store_id': store.id,
                'store_name': store.name,
                'offer_ids': [lst.store_listing_id for lst in listings],
                'error': str(e),
            },
            integration_account=store,
        )
        for lst in listings:
            results[lst.id] = False


def _delete_one_listing(listing: Listing, *, proxy_pool=None) -> bool:
    """Delete a single marketplace offer and mark listing as CLOSED.

    Returns True on success (including when store/credential is missing),
    False if the marketplace API call raised an exception.
    """
    store = listing.integration_account
    if not store or not store.credential:
        # Store gone — mark deleted locally, nothing to delete remotely
        listing.status = ListingStatus.DELETED
        listing.removed_at = timezone.now()
        listing.save(update_fields=['status', 'removed_at'])
        return True

    marketplace = store.provider
    try:
        provider = registry.get_provider(marketplace)
        facade = registry.get_or_build_client(marketplace, store.credential, proxy_pool=proxy_pool)
        provider.delete_listing(facade, listing.store_listing_id)
    except Exception as e:
        logger.warning(
            "Failed to delete offer %s on %s: %s",
            listing.store_listing_id, marketplace, e,
        )
        PostingLog.objects.create(
            task_name='dropship_cleaner',
            level=PostingLogLevel.ERROR,
            message=f"Delete offer failed: {listing.store_listing_id} on {marketplace}",
            detail={
                'listing_id': listing.id,
                'store_listing_id': listing.store_listing_id,
                'marketplace': marketplace,
                'error': str(e),
            },
            integration_account=store,
        )
        return False

    listing.status = ListingStatus.DELETED
    listing.removed_at = timezone.now()
    listing.save(update_fields=['status', 'removed_at'])
    return True
