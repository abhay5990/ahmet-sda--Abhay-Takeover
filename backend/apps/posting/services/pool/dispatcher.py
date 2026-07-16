"""Pool dispatch service — reserve items and launch a new-offer PostingJob.

This module handles the "Create Offer from Pool" flow (TASK-079):

1. ``reserve_pending_items_for_new_offer`` — atomically moves PENDING items to
   RESERVED under a new PoolDispatchReservation.
2. ``release_reserved_items`` — rolls back to PENDING (known-safe) or marks
   FAILED+unknown (remote outcome uncertain).
3. ``finalize_reserved_items_for_new_offer`` — after successful job, creates
   PoolOffer and marks reserved items PUSHED.
4. ``dispatch_offer_from_pool`` — orchestrates the full dispatch: reserve →
   build job → launch via on_commit.

None of these functions import from API layers (no JsonResponse, no request
objects). Job launch is via ``transaction.on_commit`` so the DB is consistent
before the background thread starts.
"""

from __future__ import annotations

import logging
import threading
import uuid as _uuid
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.posting.models import (
    OfferPool,
    OfferPoolItem,
    OfferPoolItemStatus,
    PoolDispatchReservation,
    PoolDispatchReservationStatus,
    PostingJob,
    PostingJobItem,
    PostingJobItemStatus,
    PostingJobStatus,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Overlay helpers
# ---------------------------------------------------------------------------

# Fields allowed in raw_data overlay — no credential fields.
_OVERLAY_WHITELIST: frozenset[str] = frozenset({
    'title',
    'description',
    'price',
    'purchased_price',
    'platform',
    'manual_fields',
    'offer_details',
    'batch_data',
    'tags',
    'account_tags',
})


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Deep-merge overlay onto base.

    - dict values: recursively merged.
    - list values: overlay replaces base (explicit override).
    - scalar values: overlay wins.

    Returns a new dict; does not mutate inputs.
    """
    result = dict(base)
    for key, val in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def build_dispatch_raw_overrides(
    items: list[OfferPoolItem],
    batch_data: dict,
) -> dict[str, dict]:
    """Build per-owned-product raw_data overlays from drawer batch_data.

    Only whitelisted non-credential fields are included in the overlay.
    The overlay is keyed by str(owned_product_id).

    Args:
        items: Reserved OfferPoolItems whose owned_products will receive the overlay.
        batch_data: Fields from the drawer (title, description, price, manual_fields…).

    Returns:
        Mapping ``{str(owned_product_id): overlay_dict}``
    """
    overlay: dict[str, Any] = {
        k: v for k, v in batch_data.items() if k in _OVERLAY_WHITELIST
    }
    if not overlay:
        return {}
    return {str(item.owned_product_id): overlay for item in items}


# ---------------------------------------------------------------------------
# Reservation primitives
# ---------------------------------------------------------------------------

def reserve_pending_items_for_new_offer(
    *,
    pool: OfferPool,
    store,  # IntegrationAccount
    count: int,
) -> PoolDispatchReservation:
    """Atomically reserve ``count`` unassigned PENDING items for a new dispatch.

    Steps:
    1. Row-lock the OfferPool.
    2. Create PoolDispatchReservation (status=ACTIVE).
    3. Select ``count`` PENDING+unassigned items with SELECT FOR UPDATE.
    4. If not enough items: release reservation, raise ValueError.
    5. Mark each item RESERVED with reservation + claimed_at set.

    Must be called inside a transaction.atomic() block.

    Raises:
        ValueError: if fewer than ``count`` unreserved PENDING items exist.
    """
    # Lock the pool row to prevent concurrent reservations racing
    locked_pool = OfferPool.objects.select_for_update().get(pk=pool.pk)

    reservation = PoolDispatchReservation.objects.create(
        pool=locked_pool,
        store=store,
        status=PoolDispatchReservationStatus.ACTIVE,
        item_count=count,
    )

    items = list(
        OfferPoolItem.objects.select_for_update().filter(
            pool=locked_pool,
            status=OfferPoolItemStatus.PENDING,
            pool_offer__isnull=True,
            reservation__isnull=True,
            claim_token__isnull=True,
        ).order_by('order', 'created_at')[:count]
    )

    if len(items) < count:
        reservation.status = PoolDispatchReservationStatus.RELEASED
        reservation.reason = f'Not enough pending items: requested {count}, available {len(items)}'
        reservation.released_at = timezone.now()
        reservation.save(update_fields=['status', 'reason', 'released_at'])
        raise ValueError(
            f'Not enough unreserved pending items in pool #{pool.pk}: '
            f'requested {count}, available {len(items)}'
        )

    now = timezone.now()
    OfferPoolItem.objects.filter(pk__in=[it.pk for it in items]).update(
        status=OfferPoolItemStatus.RESERVED,
        reservation=reservation,
        claimed_at=now,
        claim_token=None,
        failure_stage='',
        remote_state='',
        error_message='',
    )

    logger.info(
        'Reserved %d items for new dispatch (pool=%d, reservation=%d)',
        count, pool.pk, reservation.pk,
    )
    return reservation


def attach_job_to_reservation(
    reservation: PoolDispatchReservation,
    job: PostingJob,
) -> None:
    """Link a PostingJob to its reservation after job creation."""
    reservation.job = job
    reservation.save(update_fields=['job_id'])


def release_reserved_items(
    reservation: PoolDispatchReservation,
    *,
    reason: str = '',
    remote_outcome: str = 'absent',
    owned_product_ids: list[int] | None = None,
) -> None:
    """Release reserved items back to PENDING or mark as FAILED+unknown.

    Args:
        reservation: The PoolDispatchReservation to release.
        reason: Human-readable explanation stored on reservation and items.
        remote_outcome: ``"absent"`` for known-safe failures (no remote side
            effect); ``"unknown"`` when the remote outcome is uncertain.
        owned_product_ids: If given, only release items for these products.
            Useful for partial releases (e.g. PA partial success).

    ``remote_outcome="absent"`` → items return to PENDING (safe to re-dispatch).
    ``remote_outcome="unknown"`` → items become FAILED+remote_state=unknown
        and must be reconciled manually.
    """
    qs = OfferPoolItem.objects.filter(
        reservation=reservation,
        status=OfferPoolItemStatus.RESERVED,
    )
    if owned_product_ids is not None:
        qs = qs.filter(owned_product_id__in=owned_product_ids)

    if remote_outcome == 'absent':
        qs.update(
            status=OfferPoolItemStatus.PENDING,
            reservation=None,
            claimed_at=None,
            failure_stage='dispatch_release',
            error_message=reason,
        )
        reservation.status = PoolDispatchReservationStatus.RELEASED
    else:
        qs.update(
            status=OfferPoolItemStatus.FAILED,
            failure_stage='dispatch_unknown',
            remote_state='unknown',
            error_message=reason,
        )
        reservation.status = PoolDispatchReservationStatus.FAILED

    reservation.reason = reason
    reservation.released_at = timezone.now()
    reservation.save(update_fields=['status', 'reason', 'released_at'])

    logger.info(
        'Released reservation #%d (outcome=%s, reason=%s)',
        reservation.pk, remote_outcome, reason,
    )


def finalize_reserved_items_for_new_offer(
    reservation: PoolDispatchReservation,
    pool_offer,  # PoolOffer
    *,
    listing,  # Listing
    owned_products: list,
) -> None:
    """Mark reserved items PUSHED and link them to the new PoolOffer.

    Called from listing_writer after successful job completion.
    Idempotent: already-PUSHED items are skipped.
    """
    now = timezone.now()
    items = list(
        OfferPoolItem.objects.select_for_update().filter(
            reservation=reservation,
            status=OfferPoolItemStatus.RESERVED,
            owned_product__in=owned_products,
        )
    )
    for item in items:
        item.status = OfferPoolItemStatus.PUSHED
        item.pool_offer = pool_offer
        item.reservation = None
        item.target_offer_id = listing.store_listing_id or ''
        item.remote_state = 'present'
        item.pushed_at = now
        item.claim_token = None
        item.claimed_at = None
        item.save(update_fields=[
            'status', 'pool_offer', 'reservation', 'target_offer_id',
            'remote_state', 'pushed_at', 'claim_token', 'claimed_at', 'updated_at',
        ])

    # Mark reservation finalized if all items are done
    remaining = OfferPoolItem.objects.filter(
        reservation=reservation,
        status=OfferPoolItemStatus.RESERVED,
    ).exists()
    if not remaining:
        reservation.status = PoolDispatchReservationStatus.FINALIZED
        reservation.finalized_at = now
        reservation.save(update_fields=['status', 'finalized_at'])

    logger.info(
        'Finalized %d items for reservation #%d -> PoolOffer #%d',
        len(items), reservation.pk, pool_offer.pk,
    )


# ---------------------------------------------------------------------------
# Job-level release (called from orchestrator/consumer failure paths)
# ---------------------------------------------------------------------------

def release_dispatch_items_for_job(
    job: PostingJob,
    *,
    owned_products: list | None = None,
    reason: str = '',
    remote_outcome: str = 'absent',
) -> None:
    """Release reserved items for a _pool_dispatch job on failure.

    Only acts when ``job.settings["_pool_dispatch"]`` is present.
    Safe to call from non-dispatch jobs (no-op).

    Args:
        job: The PostingJob that failed.
        owned_products: Subset of OwnedProducts to release. None = release all.
        reason: Human-readable failure reason.
        remote_outcome: ``"absent"`` or ``"unknown"`` (see release_reserved_items).
    """
    pool_dispatch = (job.settings or {}).get('_pool_dispatch')
    if not pool_dispatch:
        return

    reservation_id = pool_dispatch.get('reservation_id')
    if not reservation_id:
        return

    try:
        reservation = PoolDispatchReservation.objects.get(
            pk=reservation_id,
            status=PoolDispatchReservationStatus.ACTIVE,
        )
    except PoolDispatchReservation.DoesNotExist:
        logger.warning(
            'release_dispatch_items_for_job: reservation #%s not found or not active (job=%d)',
            reservation_id, job.pk,
        )
        return

    owned_product_ids: list[int] | None = None
    if owned_products is not None:
        owned_product_ids = [op.pk for op in owned_products if op is not None]

    release_reserved_items(
        reservation,
        reason=reason,
        remote_outcome=remote_outcome,
        owned_product_ids=owned_product_ids,
    )


# ---------------------------------------------------------------------------
# Main dispatch entry point
# ---------------------------------------------------------------------------

def dispatch_offer_from_pool(
    *,
    pool: OfferPool,
    store,  # IntegrationAccount
    count: int,
    target_count: int,
    threshold: int,
    max_concurrent: int | None,
    batch_data: dict,
    store_settings: dict,
    media_settings: dict,
) -> PostingJob:
    """Reserve pool items and create a PostingJob for a new offer.

    Reservation + job creation run inside a single transaction. The
    orchestrator is launched via ``transaction.on_commit`` so the DB is
    consistent before the background thread starts.

    Returns:
        The newly-created PostingJob.

    Raises:
        ValueError: validation failures (not enough items, etc.)
    """
    from apps.posting.models import PoolOffer

    strategy = PoolOffer.strategy_for_provider(store.provider)

    with transaction.atomic():
        reservation = reserve_pending_items_for_new_offer(
            pool=pool,
            store=store,
            count=count,
        )

        # Fetch reserved items with their owned_products
        items = list(
            reservation.items.select_related('owned_product').all()
        )
        owned_products = [it.owned_product for it in items]

        # Attach the validated pre-fed image to the established manual batch
        # contract used by the stock payload pipeline.
        effective_batch_data = dict(batch_data)
        effective_batch_data.update(media_settings)

        # Build raw_data overlays from drawer fields (whitelist only)
        raw_overrides = build_dispatch_raw_overrides(items, effective_batch_data)

        # Determine source_type for manual payload path
        source_type = 'manual'

        # Build job settings
        job_settings: dict = {
            store.slug: store_settings,
            '_media': media_settings,
            '_manual': {
                'source_type': source_type,
                'platform': effective_batch_data.get('platform', ''),
                'batch_data': effective_batch_data,
            },
            '_pool_dispatch': {
                'pool_id': pool.pk,
                'reservation_id': reservation.pk,
                'reservation_token': str(reservation.token),
                'reserved_item_ids': [it.pk for it in items],
                'target_count': target_count,
                'threshold': threshold,
                'max_concurrent': max_concurrent,
                'strategy': strategy,
                'raw_overrides': raw_overrides,
            },
        }

        job = PostingJob.objects.create(
            game=pool.game,
            settings=job_settings,
            status=PostingJobStatus.PENDING,
            total_count=count,
        )

        # Create PostingJobItems for each owned_product × store
        for owned_product in owned_products:
            PostingJobItem.objects.create(
                job=job,
                login=owned_product.login,
                owned_product=owned_product,
                store=store,
                marketplace=store.provider,
                status=PostingJobItemStatus.PENDING,
            )

        attach_job_to_reservation(reservation, job)

        # Launch orchestrator after commit so DB is fully consistent
        transaction.on_commit(lambda: _launch_orchestrator(job.pk))

    logger.info(
        'dispatch_offer_from_pool: job #%d created for pool #%d '
        '(reservation #%d, count=%d, store=%s)',
        job.pk, pool.pk, reservation.pk, count, store.name,
    )
    return job


def _launch_orchestrator(job_id: int) -> None:
    """Launch StockOrchestrator in a daemon thread after transaction commit."""
    from apps.posting.services.stock import StockOrchestrator
    # Import tracking dict from stock API to reuse duplicate-launch guard
    try:
        from apps.posting.api.stock import _active_jobs, _jobs_lock, _run_job
        with _jobs_lock:
            if job_id in _active_jobs:
                logger.warning('dispatch: job #%d already running, skipping launch', job_id)
                return
            thread = threading.Thread(
                target=_run_job,
                args=(job_id,),
                daemon=True,
                name=f'posting-job-{job_id}',
            )
            _active_jobs[job_id] = thread
            thread.start()
    except Exception:
        logger.exception('dispatch: failed to launch orchestrator for job #%d', job_id)
