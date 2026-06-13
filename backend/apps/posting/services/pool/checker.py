"""Offer pool checker — two trigger mechanisms:

1. Reactive: called by order sync when a sale is detected on a pool-linked listing.
2. Proactive: periodic sweep (every 30 min) checks all active pools against remote.
"""
from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone

from apps.integrations.providers.registry import get_or_build_client
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.posting.models import (
    OfferPool,
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    OfferPoolStatus,
    PostingLog,
    PostingLogLevel,
)

from .replenisher import (
    _create_eldorado_offer,
    _is_gameboost_legacy_payload,
    _mark_items_pushed,
    _reconcile_pushed_items,
    replenish_pool,
)
from apps.posting.services.shared.utils import extract_listing_id
from core.marketplace.payload_extractor import extract_create_payload

logger = logging.getLogger(__name__)

TASK_NAME = 'pool_checker'

# Sentinel: offer no longer exists on remote (404)
_OFFER_NOT_FOUND = -1


# ── Reactive trigger (called from order sync) ────────────────────


def notify_sale(listing_id: int) -> None:
    """Called when an order is detected for a listing.

    Reactive path — triggered by order sync services.
    Optimistic local decrement: no API call needed to decide whether to replenish.
    """
    # Eldorado / Gameboost pools linked directly to this listing
    pools = OfferPool.objects.filter(
        listing_id=listing_id,
        status=OfferPoolStatus.ACTIVE,
    ).select_related('listing', 'store', 'store__credential', 'game')

    for pool in pools:
        try:
            _on_sale_detected(pool)
        except Exception:
            logger.exception('pool_checker: reactive check failed for pool %d', pool.pk)

    # PA clone pools where the listing is an active offer
    active_offers = OfferPoolActiveOffer.objects.filter(
        listing_id=listing_id,
        status=OfferPoolActiveOfferStatus.ACTIVE,
    ).select_related('pool', 'pool__listing', 'pool__store', 'pool__store__credential', 'pool__game')

    for ao in active_offers:
        try:
            ao.status = OfferPoolActiveOfferStatus.SOLD
            ao.save(update_fields=['status', 'updated_at'])
            _on_sale_detected(ao.pool)
        except Exception:
            logger.exception('pool_checker: reactive PA check failed for active_offer %d', ao.pk)


def _on_sale_detected(pool: OfferPool) -> int:
    """Optimistic decrement + threshold check — no API call needed.

    For append pools (Eldorado/Gameboost): decrement current_remote_count by 1.
    For clone pools (PA): recount active offers from DB.
    If below threshold → trigger replenish immediately.
    """
    marketplace = pool.store.provider
    now = timezone.now()

    if marketplace == 'playerauctions':
        # PA: count active offers from DB (already accurate after SOLD update)
        remote_count = pool.active_offers.filter(
            status=OfferPoolActiveOfferStatus.ACTIVE,
        ).count()
        pool.current_remote_count = remote_count
        pool.last_checked_at = now
        pool.save(update_fields=['current_remote_count', 'last_checked_at', 'updated_at'])

        if remote_count < pool.max_concurrent:
            return replenish_pool(pool)
        return 0

    # Eldorado / Gameboost: optimistic decrement
    if pool.current_remote_count is not None and pool.current_remote_count > 0:
        pool.current_remote_count -= 1
    elif pool.current_remote_count is None:
        # First sale but never checked — set to 0, replenish will fetch real count
        pool.current_remote_count = 0

    pool.last_checked_at = now
    pool.save(update_fields=['current_remote_count', 'last_checked_at', 'updated_at'])

    logger.info(
        'pool_checker: sale detected for pool %d, remote_count decremented to %s (threshold=%d)',
        pool.pk, pool.current_remote_count, pool.threshold,
    )

    if pool.current_remote_count is not None and pool.current_remote_count < pool.threshold:
        PostingLog.objects.create(
            task_name=TASK_NAME,
            level=PostingLogLevel.INFO,
            message=f"Pool #{pool.pk}: sale detected, count={pool.current_remote_count} < threshold={pool.threshold}, triggering replenish",
            detail={'pool_id': pool.pk, 'remote_count': pool.current_remote_count, 'threshold': pool.threshold},
        )
        return replenish_pool(pool)

    return 0


# ── Proactive sweep (called by scheduler every 30 min) ───────────


def sweep_all_pools() -> dict[str, int]:
    """Check all active pools and replenish where needed.

    Returns summary stats: {checked, replenished, errors}.
    """
    pools = list(
        OfferPool.objects.filter(
            status=OfferPoolStatus.ACTIVE,
        ).select_related('listing', 'store', 'store__credential', 'game')
    )

    stats = {'checked': 0, 'replenished': 0, 'errors': 0}

    for pool in pools:
        try:
            stats['checked'] += 1
            pushed = _check_and_replenish(pool)
            if pushed > 0:
                stats['replenished'] += 1
        except Exception:
            logger.exception('pool_checker: sweep failed for pool %d', pool.pk)
            stats['errors'] += 1

    if stats['checked'] > 0:
        PostingLog.objects.create(
            task_name=TASK_NAME,
            level=PostingLogLevel.INFO,
            message=f"Pool sweep: {stats['checked']} checked, {stats['replenished']} replenished, {stats['errors']} errors",
            detail=stats,
        )

    return stats


# ── Internal ─────────────────────────────────────────────────────


def _check_and_replenish(pool: OfferPool, *, force: bool = False) -> int:
    """Fetch remote credential count, reconcile stale items, then replenish if needed.

    Args:
        force: If True, replenish even when remote count >= threshold.
               Used for manual "Replenish Now" triggers.
    """
    marketplace = pool.store.provider

    if marketplace == 'playerauctions':
        remote_count = _get_pa_active_count(pool)
        remote_creds = None
    else:
        remote_count, remote_creds = _get_remote_credentials(pool, marketplace)

    # Offer gone from remote — recover by creating a new one
    if remote_count == _OFFER_NOT_FOUND:
        pool.current_remote_count = 0
        pool.last_checked_at = timezone.now()
        pool.save(update_fields=['current_remote_count', 'last_checked_at', 'updated_at'])
        return _recover_missing_offer(pool, marketplace)

    pool.current_remote_count = remote_count
    pool.last_checked_at = timezone.now()
    pool.save(update_fields=['current_remote_count', 'last_checked_at', 'updated_at'])

    # Reconcile: mark PUSHED items no longer on remote as CONSUMED
    if remote_creds is not None:
        _reconcile_pushed_items(pool, remote_creds)

    if remote_count is not None and remote_count < pool.threshold:
        return replenish_pool(pool)

    # Force mode: replenish regardless of threshold (manual trigger)
    if force:
        if remote_count is None:
            logger.info('pool_checker: force replenish for pool %d (remote count unavailable)', pool.pk)
        else:
            logger.info('pool_checker: force replenish for pool %d (remote=%d, threshold=%d)', pool.pk, remote_count, pool.threshold)
        return replenish_pool(pool)

    return 0


def _get_remote_credentials(
    pool: OfferPool,
    marketplace: str,
) -> tuple[int | None, list[str] | None]:
    """Query marketplace API for current credentials on the offer.

    Returns (count, credential_strings).
    credential_strings is None when API call fails or format doesn't support it.
    """
    store = pool.store
    proxy_pool = build_proxy_pool()
    proxy_group = get_group_name(store)
    client = get_or_build_client(
        marketplace,
        store.credential,
        proxy_pool=proxy_pool,
        proxy_group=proxy_group,
    )

    offer_id = pool.listing.store_listing_id

    if marketplace == 'eldorado':
        return _fetch_eldorado(client, offer_id, proxy_group, pool)
    elif marketplace == 'gameboost':
        return _fetch_gameboost(client, offer_id, proxy_group, pool)

    return None, None


def _fetch_eldorado(
    client: Any,
    offer_id: str,
    proxy_group: str | None,
    pool: OfferPool,
) -> tuple[int | None, list[str] | None]:
    """Eldorado: GET account details, return count + credential strings.

    Returns (_OFFER_NOT_FOUND, None) when the offer no longer exists (404).
    """
    result = client.get_offer_account_details(offer_id, proxy_group=proxy_group)
    if not result.ok:
        status_code = getattr(result.error, 'status_code', None)
        if status_code == 404:
            logger.warning(
                'pool_checker: Eldorado offer %s not found (404)', offer_id,
            )
            return _OFFER_NOT_FOUND, None
        logger.warning(
            'pool_checker: Eldorado count failed for offer %s: %s',
            offer_id, result.error,
        )
        return None, None

    resp = result.data
    creds: list[str] = []
    if hasattr(resp, 'secretDetails') and resp.secretDetails:
        creds = [entry.secretDetails for entry in resp.secretDetails if entry.secretDetails]
    elif hasattr(resp, 'accountsDetails') and resp.accountsDetails:
        creds = [entry.secretDetails for entry in resp.accountsDetails if entry.secretDetails]
    return len(creds), creds


def _fetch_gameboost(
    client: Any,
    offer_id: str,
    proxy_group: str | None,
    pool: OfferPool,
) -> tuple[int | None, list[str] | None]:
    """Gameboost: detect format from DB, then fetch credentials via API.

    Old format (payload has login/password): single credential, count = 0 or 1.
    New format (payload has credentials list): fetch via /credentials endpoint.
    """
    is_legacy = _is_gameboost_legacy_payload(pool.listing)

    if is_legacy:
        # Legacy: get_offer to check if the single credential is still there
        offer_result = client.get_offer(offer_id, proxy_group=proxy_group)
        if not offer_result.ok:
            logger.warning(
                'pool_checker: Gameboost get_offer failed for %s: %s',
                offer_id, offer_result.error,
            )
            return None, None
        offer = offer_result.data
        has_cred = (
            offer.credentials
            and getattr(offer.credentials, 'login', None)
        )
        # Legacy single-credential: can't do string reconciliation
        return (1 if has_cred else 0), None

    # New format: fetch via /credentials endpoint
    result = client.list_offer_credentials(offer_id, proxy_group=proxy_group)
    if not result.ok:
        logger.warning(
            'pool_checker: Gameboost count failed for offer %s: %s',
            offer_id, result.error,
        )
        return None, None

    data = result.data
    if isinstance(data, list):
        creds = [str(c) for c in data if c]
        return len(creds), creds
    if hasattr(data, 'total'):
        return data.total, None
    return 0, []


def _get_pa_active_count(pool: OfferPool) -> int:
    """PA: count active clone offers from our DB (no API call needed)."""
    return pool.active_offers.filter(
        status=OfferPoolActiveOfferStatus.ACTIVE,
    ).count()


def _recover_missing_offer(pool: OfferPool, marketplace: str) -> int:
    """Recreate an offer that no longer exists on remote (404).

    Builds a new offer from the listing's original payload, attaches
    existing PUSHED credentials, and links the pool to the new offer.
    """
    if marketplace != 'eldorado':
        # Only Eldorado recovery supported for now
        PostingLog.objects.create(
            task_name=TASK_NAME,
            level=PostingLogLevel.WARNING,
            message=f"Pool #{pool.pk}: offer missing on {marketplace}, cannot auto-recover",
            detail={'pool_id': pool.pk},
            integration_account=pool.store,
        )
        return 0

    listing = pool.listing
    old_offer_id = listing.store_listing_id

    # Extract original payload
    raw = listing.raw_data or {}
    original_payload = extract_create_payload(raw, 'eldorado')
    if not original_payload:
        PostingLog.objects.create(
            task_name=TASK_NAME,
            level=PostingLogLevel.ERROR,
            message=f"Pool #{pool.pk}: cannot recover — no original payload in listing.raw_data",
            integration_account=pool.store,
        )
        return 0

    # Gather existing PUSHED credentials (still valid, just lost their remote offer)
    from .formatter import format_credential_for_marketplace
    from apps.posting.models import OfferPoolItem, OfferPoolItemStatus

    pushed_items = list(
        pool.items.filter(status=OfferPoolItemStatus.PUSHED)
        .select_related('owned_product')
    )

    existing_creds: list[str] = []
    valid_items: list[OfferPoolItem] = []
    for item in pushed_items:
        try:
            cred_str = format_credential_for_marketplace(item.owned_product, 'eldorado', pool=pool)
            existing_creds.append(cred_str)
            valid_items.append(item)
        except Exception:
            pass

    # If no pushed creds, use the credentials from the original payload
    if not existing_creds:
        existing_creds = original_payload.get('accountSecretDetails', [])
        if isinstance(existing_creds, str):
            existing_creds = [existing_creds] if existing_creds else []

    if not existing_creds:
        PostingLog.objects.create(
            task_name=TASK_NAME,
            level=PostingLogLevel.ERROR,
            message=f"Pool #{pool.pk}: cannot recover — no credentials to create offer with",
            integration_account=pool.store,
        )
        return 0

    PostingLog.objects.create(
        task_name=TASK_NAME,
        level=PostingLogLevel.INFO,
        message=f"Pool #{pool.pk}: offer {old_offer_id} missing on remote, recovering with {len(existing_creds)} cred(s)",
        detail={'pool_id': pool.pk, 'old_offer_id': old_offer_id},
        integration_account=pool.store,
    )

    # Build client and create new offer (no delete needed — already gone)
    store = pool.store
    proxy_pool = build_proxy_pool()
    proxy_group = get_group_name(store)
    client = get_or_build_client(
        'eldorado',
        store.credential,
        proxy_pool=proxy_pool,
        proxy_group=proxy_group,
    )

    pushed = _create_eldorado_offer(
        pool, client, original_payload, existing_creds, valid_items, proxy_group,
    )

    if pushed > 0:
        # Trigger normal replenish to fill up to target
        replenish_pool(pool)

    return pushed
