"""Offer pool checker — two trigger mechanisms:

1. Reactive: called by order sync when a sale is detected on a pool-linked listing.
2. Proactive: periodic sweep (every 30 min) checks all active pools against remote.
"""
from __future__ import annotations

import logging
import hashlib
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.integrations.providers.registry import get_or_build_client
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.posting.models import (
    OfferPool,
    OfferPoolActiveOffer,
    OfferPoolActiveOfferStatus,
    PoolOffer,
    PoolOfferStatus,
    PoolSaleEvent,
    PostingLog,
    PostingLogLevel,
)

from .replenisher import (
    _create_eldorado_offer,
    _is_gameboost_legacy_payload,
    _mark_items_pushed,
    _PoolOfferContext,
    _reconcile_pushed_items,
    replenish_pool_offer,
)
from .allocation import quarantine_stale_claims
from apps.posting.services.shared.utils import extract_listing_id
from core.marketplace.payload_extractor import extract_create_payload

logger = logging.getLogger(__name__)

TASK_NAME = 'pool_checker'

# Sentinel: offer no longer exists on remote (404)
_OFFER_NOT_FOUND = -1


# ── Reactive trigger (called from order sync) ────────────────────


def notify_sale(
    listing_id: int,
    *,
    event_key: str | None = None,
    order_id: int | None = None,
) -> None:
    """Called when an order is detected for a listing.

    Reactive path — triggered by order sync services.
    Optimistic local decrement: no API call needed to decide whether to replenish.
    """
    base_event_key = event_key or f'legacy-listing:{listing_id}:{timezone.now().timestamp()}'

    # Append offers and the PA source/template listing.
    pool_offers = PoolOffer.objects.filter(
        listing_id=listing_id,
        strategy='append',
    ).exclude(status=PoolOfferStatus.DETACHED).select_related(
        'pool', 'pool__game', 'listing', 'listing__integration_account',
        'listing__integration_account__credential',
    )

    for pool_offer in pool_offers:
        try:
            should_replenish = _record_sale_event(
                pool_offer,
                listing_id=listing_id,
                event_key=f'{base_event_key}:offer:{pool_offer.pk}',
                order_id=order_id,
            )
            if should_replenish:
                replenish_pool_offer(pool_offer)
        except Exception:
            logger.exception(
                'pool_checker: reactive check failed for pool_offer %d',
                pool_offer.pk,
            )

    # PA clone pools where the listing is an active offer
    active_offers = OfferPoolActiveOffer.objects.filter(
        listing_id=listing_id,
        status=OfferPoolActiveOfferStatus.ACTIVE,
        pool_offer__isnull=False,
    ).select_related(
        'pool_offer', 'pool_offer__pool', 'pool_offer__listing',
        'pool_offer__listing__integration_account',
    )

    for ao in active_offers:
        try:
            should_replenish = _record_sale_event(
                ao.pool_offer,
                listing_id=listing_id,
                event_key=f'{base_event_key}:active-offer:{ao.pk}',
                order_id=order_id,
                active_offer=ao,
            )
            if should_replenish:
                replenish_pool_offer(ao.pool_offer)
        except Exception:
            logger.exception('pool_checker: reactive PA check failed for active_offer %d', ao.pk)


def _record_sale_event(
    pool_offer: PoolOffer,
    *,
    listing_id: int,
    event_key: str,
    order_id: int | None,
    active_offer: OfferPoolActiveOffer | None = None,
) -> bool | None:
    """Persist sale deduplication and the PA SOLD transition atomically."""
    if len(event_key) > 255:
        digest = hashlib.sha256(event_key.encode()).hexdigest()
        event_key = f'{event_key[:180]}:{digest}'
    with transaction.atomic():
        event, created = PoolSaleEvent.objects.get_or_create(
            event_key=event_key,
            defaults={
                'listing_id': listing_id,
                'pool_offer': pool_offer,
                'order_id': order_id,
                'outcome': 'processing',
            },
        )
        if not created:
            return None
        if active_offer is not None:
            locked = OfferPoolActiveOffer.objects.select_for_update().get(
                pk=active_offer.pk,
            )
            if locked.status != OfferPoolActiveOfferStatus.ACTIVE:
                event.outcome = 'already_processed'
                event.processed_at = timezone.now()
                event.save(update_fields=['outcome', 'processed_at'])
                return None
            locked.status = OfferPoolActiveOfferStatus.SOLD
            locked.save(update_fields=['status', 'updated_at'])
        locked_offer = (
            PoolOffer.objects.select_for_update()
            .select_related('pool', 'listing', 'listing__integration_account')
            .get(pk=pool_offer.pk)
        )
        now = timezone.now()
        if locked_offer.marketplace == 'playerauctions':
            remote_count = locked_offer.active_offers.filter(
                status=OfferPoolActiveOfferStatus.ACTIVE,
            ).count()
        else:
            remote_count = locked_offer.current_remote_count
            if remote_count is None:
                remote_count = 0
            elif remote_count > 0:
                remote_count -= 1

        locked_offer.current_remote_count = remote_count
        locked_offer.last_checked_at = now
        locked_offer.save(update_fields=[
            'current_remote_count', 'last_checked_at', 'updated_at',
        ])
        event.outcome = 'processed'
        event.processed_at = now
        event.pool_offer = locked_offer
        event.save(update_fields=['outcome', 'processed_at', 'pool_offer'])
        should_replenish = (
            remote_count < locked_offer.threshold
            and locked_offer.can_replenish
        )

    logger.info(
        'pool_checker: sale event %s processed for pool_offer %d, count=%s',
        event.event_key, locked_offer.pk, remote_count,
    )
    return should_replenish


# ── Proactive sweep (called by scheduler every 30 min) ───────────


def sweep_all_pools() -> dict[str, int]:
    """Monitor all managed offers and replenish only active ones.

    Returns summary stats: {checked, replenished, errors}.
    """
    quarantine_stale_claims()
    pool_offers = list(
        PoolOffer.objects.exclude(status=PoolOfferStatus.DETACHED).select_related(
            'pool', 'pool__game', 'pool__credential_spec',
            'listing', 'listing__integration_account',
            'listing__integration_account__credential',
        )
    )
    pool_offers.sort(key=lambda offer: (
        offer.pool_id,
        -1 if offer.current_remote_count is None else (
            offer.current_remote_count / max(offer.target_count, 1)
        ),
        offer.last_replenished_at.timestamp() if offer.last_replenished_at else 0,
        offer.pk,
    ))

    stats = {'checked': 0, 'replenished': 0, 'errors': 0}

    for pool_offer in pool_offers:
        try:
            stats['checked'] += 1
            pushed = _check_and_replenish(pool_offer)
            if pushed > 0:
                stats['replenished'] += 1
        except Exception:
            logger.exception(
                'pool_checker: sweep failed for pool_offer %d', pool_offer.pk,
            )
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


def _check_and_replenish(pool_offer: PoolOffer, *, force: bool = False) -> int:
    """Fetch remote credential count, reconcile stale items, then replenish if needed.

    Args:
        force: If True, replenish even when remote count >= threshold.
               Used for manual "Replenish Now" triggers.
    """
    pool_offer = PoolOffer.objects.select_related(
        'pool', 'pool__game', 'pool__credential_spec',
        'listing', 'listing__integration_account',
        'listing__integration_account__credential',
    ).get(pk=pool_offer.pk)
    pool = _PoolOfferContext(pool_offer)
    marketplace = pool_offer.marketplace

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

    # A failed/unknown monitor result must not be interpreted as zero stock;
    # doing so could duplicate every credential on the remote offer.
    if remote_count is None:
        logger.warning(
            'pool_checker: remote count unavailable for pool_offer %d; replenish skipped',
            pool_offer.pk,
        )
        return 0

    if remote_count < pool.threshold:
        return replenish_pool_offer(pool_offer)

    # Force mode: replenish regardless of threshold (manual trigger)
    if force:
        if remote_count is None:
            logger.info('pool_checker: force replenish for pool %d (remote count unavailable)', pool.pk)
        else:
            logger.info('pool_checker: force replenish for pool %d (remote=%d, threshold=%d)', pool.pk, remote_count, pool.threshold)
        return replenish_pool_offer(pool_offer)

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


def _get_pa_active_count(pool: OfferPool) -> int | None:
    """Reconcile local PA ActiveOffers against remote offer existence."""
    active_offers = list(
        pool.active_offers.filter(status=OfferPoolActiveOfferStatus.ACTIVE)
        .select_related('pool_item')
    )
    if not active_offers:
        return 0

    store = pool.store
    proxy_pool = build_proxy_pool()
    proxy_group = get_group_name(store)
    client = get_or_build_client(
        'playerauctions',
        store.credential,
        proxy_pool=proxy_pool,
        proxy_group=proxy_group,
    )
    for active_offer in active_offers:
        result = client.get_offer_details(
            active_offer.store_listing_id,
            proxy_group=proxy_group,
        )
        if result.ok:
            continue
        status_code = getattr(result.error, 'status_code', None)
        if status_code != 404:
            logger.warning(
                'pool_checker: PA offer %s could not be verified: %s',
                active_offer.store_listing_id,
                result.error,
            )
            return None
        with transaction.atomic():
            locked = OfferPoolActiveOffer.objects.select_for_update().get(
                pk=active_offer.pk,
            )
            if locked.status != OfferPoolActiveOfferStatus.ACTIVE:
                continue
            locked.status = OfferPoolActiveOfferStatus.DELISTED
            locked.save(update_fields=['status', 'updated_at'])
            if locked.pool_item_id:
                from apps.posting.models import OfferPoolItemStatus
                locked.pool_item.status = OfferPoolItemStatus.FAILED
                locked.pool_item.failure_stage = 'pa_remote_missing'
                locked.pool_item.remote_state = 'absent'
                locked.pool_item.error_message = 'PA offer missing during reconciliation'
                locked.pool_item.save(update_fields=[
                    'status', 'failure_stage', 'remote_state',
                    'error_message', 'updated_at',
                ])
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
        pool.items.filter(
            status=OfferPoolItemStatus.PUSHED,
            pool_offer=pool.pool_offer,
        )
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
        replenish_pool_offer(pool.pool_offer)

    return pushed
