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

from .replenisher import _is_gameboost_legacy_payload, replenish_pool

logger = logging.getLogger(__name__)

TASK_NAME = 'pool_checker'


# ── Reactive trigger (called from order sync) ────────────────────


def notify_sale(listing_id: int) -> None:
    """Called when an order is detected for a listing. Check if pool needs replenish.

    This is the reactive path — triggered by order sync services.
    Intentionally lightweight: just checks and triggers replenish if needed.
    """
    pools = OfferPool.objects.filter(
        listing_id=listing_id,
        status=OfferPoolStatus.ACTIVE,
    ).select_related('listing', 'store', 'store__credential', 'game')

    for pool in pools:
        try:
            _check_and_replenish(pool)
        except Exception:
            logger.exception('pool_checker: reactive check failed for pool %d', pool.pk)

    # Also check PA clone pools where the listing is an active offer
    active_offers = OfferPoolActiveOffer.objects.filter(
        listing_id=listing_id,
        status=OfferPoolActiveOfferStatus.ACTIVE,
    ).select_related('pool', 'pool__listing', 'pool__store', 'pool__store__credential', 'pool__game')

    for ao in active_offers:
        try:
            ao.status = OfferPoolActiveOfferStatus.SOLD
            ao.save(update_fields=['status', 'updated_at'])
            _check_and_replenish(ao.pool)
        except Exception:
            logger.exception('pool_checker: reactive PA check failed for active_offer %d', ao.pk)


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
    """Fetch remote credential count, then replenish if below threshold.

    Args:
        force: If True, replenish even when remote count cannot be fetched.
               Used for manual "Replenish Now" triggers.
    """
    marketplace = pool.store.provider

    if marketplace == 'playerauctions':
        remote_count = _get_pa_active_count(pool)
    else:
        remote_count = _get_remote_credential_count(pool, marketplace)

    pool.current_remote_count = remote_count
    pool.last_checked_at = timezone.now()
    pool.save(update_fields=['current_remote_count', 'last_checked_at', 'updated_at'])

    if remote_count is not None and remote_count < pool.threshold:
        return replenish_pool(pool)

    # Force mode: count alınamadıysa bile replenish yap (manual trigger)
    if force and remote_count is None:
        logger.info('pool_checker: force replenish for pool %d (remote count unavailable)', pool.pk)
        return replenish_pool(pool)

    return 0


def _get_remote_credential_count(pool: OfferPool, marketplace: str) -> int | None:
    """Query marketplace API for current credential count on the offer."""
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
        return _count_eldorado(client, offer_id, proxy_group, pool)
    elif marketplace == 'gameboost':
        return _count_gameboost(client, offer_id, proxy_group, pool)

    return None


def _count_eldorado(client: Any, offer_id: str, proxy_group: str | None, pool: OfferPool) -> int | None:
    """Eldorado: GET account details, count secretDetails entries."""
    result = client.get_offer_account_details(offer_id, proxy_group=proxy_group)
    if not result.ok:
        logger.warning(
            'pool_checker: Eldorado count failed for offer %s: %s',
            offer_id, result.error,
        )
        return None

    resp = result.data
    if hasattr(resp, 'secretDetails') and resp.secretDetails:
        return len(resp.secretDetails)
    if hasattr(resp, 'accountsDetails') and resp.accountsDetails:
        return len(resp.accountsDetails)
    return 0


def _count_gameboost(client: Any, offer_id: str, proxy_group: str | None, pool: OfferPool) -> int | None:
    """Gameboost: detect format from DB, then count credentials via API.

    Old format (payload has login/password): single credential, count = 0 or 1.
    New format (payload has credentials list): count via /credentials endpoint.
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
            return None
        offer = offer_result.data
        has_cred = (
            offer.credentials
            and getattr(offer.credentials, 'login', None)
        )
        return 1 if has_cred else 0

    # New format: count via /credentials endpoint
    result = client.list_offer_credentials(offer_id, proxy_group=proxy_group)
    if not result.ok:
        logger.warning(
            'pool_checker: Gameboost count failed for offer %s: %s',
            offer_id, result.error,
        )
        return None

    data = result.data
    if isinstance(data, list):
        return len(data)
    if hasattr(data, 'total'):
        return data.total
    return 0


def _get_pa_active_count(pool: OfferPool) -> int:
    """PA: count active clone offers from our DB (no API call needed)."""
    return pool.active_offers.filter(
        status=OfferPoolActiveOfferStatus.ACTIVE,
    ).count()
