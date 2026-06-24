"""Background batch processor for RobuxCrate orders.

Called periodically by APScheduler (runapscheduler command).
Picks up batches whose orders are still PENDING and sends them to the
RbxCrate API one by one.  Network timeouts yield an UNKNOWN status that
is later reconciled via ``get_order_info``.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apis_sdk.core.enums import ErrorCategory
from apps.integrations.models import ServiceCredential
from apps.integrations.services.robuxcrate import RobuxCrateService
from apps.tools.models import RobuxCrateBatch, RobuxCrateOrder

logger = logging.getLogger(__name__)

# Provider status → internal status mapping
_STATUS_MAP: dict[str, str] = {
    'queued': RobuxCrateOrder.Status.QUEUED,
    'in_progress': RobuxCrateOrder.Status.PROGRESS,
    'inprogress': RobuxCrateOrder.Status.PROGRESS,
    'completed': RobuxCrateOrder.Status.COMPLETED,
    'done': RobuxCrateOrder.Status.COMPLETED,
    'error': RobuxCrateOrder.Status.ERROR,
    'failed': RobuxCrateOrder.Status.ERROR,
    'cancelled': RobuxCrateOrder.Status.CANCELLED,
    'canceled': RobuxCrateOrder.Status.CANCELLED,
}


def map_provider_status(raw: str) -> str:
    """Map a raw provider status string to an internal Status value.

    Unknown values map to UNKNOWN so they are visible to operators.
    """
    return _STATUS_MAP.get(raw.lower().strip(), RobuxCrateOrder.Status.UNKNOWN)


# Error categories where the request may have reached the provider
# but we didn't get a definitive response back.
_UNCERTAIN_CATEGORIES = frozenset({
    ErrorCategory.NETWORK,
    ErrorCategory.TIMEOUT,
    ErrorCategory.UNKNOWN,
    ErrorCategory.SERVER_ERROR,
})


def _is_uncertain_error(result) -> bool:
    """Check if a failed result represents an uncertain error (request may have been processed)."""
    if not result.error:
        return False
    return result.error.category in _UNCERTAIN_CATEGORIES


# ── Public entry point (called by APScheduler) ───────────────────

def process_pending_batches() -> None:
    """Find batches with unprocessed orders and send them to RbxCrate."""
    batch_ids = list(
        RobuxCrateBatch.objects
        .filter(status__in=[RobuxCrateBatch.Status.PENDING, RobuxCrateBatch.Status.PROCESSING])
        .values_list('id', flat=True)[:50]
    )
    if not batch_ids:
        return

    # Resolve credential once for all batches
    try:
        cred = ServiceCredential.objects.get(slug='game-service-rbxcrate', is_active=True)
    except ServiceCredential.DoesNotExist:
        logger.error('RbxCrate credential not found or inactive — skipping batch processing')
        return

    creds = cred.credentials or {}
    if not creds.get('api_key'):
        logger.error('RbxCrate credential has no api_key — skipping batch processing')
        return

    client = RobuxCrateService.build_client(cred)

    for batch_id in batch_ids:
        try:
            _process_batch(batch_id, client)
        except Exception:
            logger.exception('Unexpected error processing batch %s', batch_id)


def _process_batch(batch_id, client) -> None:
    """Process a single batch: send pending orders, reconcile unknowns, update aggregate status."""
    try:
        batch = RobuxCrateBatch.objects.get(id=batch_id)
    except RobuxCrateBatch.DoesNotExist:
        return

    # Mark as processing
    if batch.status == RobuxCrateBatch.Status.PENDING:
        batch.status = RobuxCrateBatch.Status.PROCESSING
        batch.save(update_fields=['status', 'updated_at'])

    # 1) Send pending orders to RbxCrate
    pending = list(batch.orders.filter(status=RobuxCrateOrder.Status.PENDING))
    for order in pending:
        _send_order(order, batch, client)

    # 2) Reconcile unknown orders via get_order_info
    unknowns = list(batch.orders.filter(status=RobuxCrateOrder.Status.UNKNOWN))
    for order in unknowns:
        _reconcile_order(order, client)

    # 3) Update batch aggregate status
    _update_batch_status(batch)


def _send_order(order: RobuxCrateOrder, batch: RobuxCrateBatch, client) -> None:
    """Send a single order to RbxCrate. Network/timeout errors → UNKNOWN status."""
    try:
        result = client.create_gamepass_order(
            order_id=str(order.id),
            roblox_username=batch.roblox_username,
            robux_amount=batch.robux_amount,
            place_id=batch.place_id,
            is_pre_order=True,
            check_ownership=False,
        )
    except Exception:
        # Facade should never raise, but safety net for truly unexpected errors
        logger.warning('Unexpected exception sending order %s — marking UNKNOWN', order.id)
        order.status = RobuxCrateOrder.Status.UNKNOWN
        order.error_message = 'Unexpected error — status uncertain, will reconcile'
        order.save(update_fields=['status', 'error_message', 'updated_at'])
        return

    now = timezone.now()
    if result.ok:
        data = result.data or {}
        raw = data.get('status', '')
        order.status = map_provider_status(raw) if raw else RobuxCrateOrder.Status.QUEUED
        order.raw_provider_status = raw
        order.rbxcrate_response = data
        order.error_message = ''
    elif _is_uncertain_error(result):
        # Network/timeout/unknown errors — request may have reached provider
        logger.warning(
            'Uncertain error sending order %s (category=%s) — marking UNKNOWN',
            order.id, result.error.category if result.error else '?',
        )
        order.status = RobuxCrateOrder.Status.UNKNOWN
        order.error_message = f'Uncertain: {result.error.message}' if result.error else 'Status uncertain'
        order.rbxcrate_response = (result.error.details if result.error else None) or {}
    else:
        # Definitive rejection (validation, auth, etc.) — safe to mark as ERROR
        order.status = RobuxCrateOrder.Status.ERROR
        order.error_message = result.error.message if result.error else 'Unknown provider error'
        order.rbxcrate_response = (result.error.details if result.error else None) or {}

    order.last_status_checked_at = now
    order.save(update_fields=[
        'status', 'raw_provider_status', 'rbxcrate_response',
        'error_message', 'last_status_checked_at', 'updated_at',
    ])


def _reconcile_order(order: RobuxCrateOrder, client) -> None:
    """Try to resolve an UNKNOWN order by querying RbxCrate for its status."""
    try:
        result = client.get_order_info(str(order.id))
    except Exception:
        logger.warning('Reconciliation failed for order %s — still UNKNOWN', order.id)
        return

    now = timezone.now()
    if result.ok:
        data = result.data or {}
        raw = data.get('status', '')
        order.status = map_provider_status(raw) if raw else RobuxCrateOrder.Status.UNKNOWN
        order.raw_provider_status = raw
        order.rbxcrate_response = data
        order.error_message = data.get('error', '') or ''
    elif _is_uncertain_error(result):
        # Network/timeout during reconciliation — leave as UNKNOWN, try again next cycle
        logger.warning('Reconciliation uncertain for order %s — still UNKNOWN', order.id)
        return
    else:
        # Definitive error (e.g. NOT_FOUND) — order was never created
        order.status = RobuxCrateOrder.Status.ERROR
        order.error_message = 'Order not found at provider after network error'

    order.last_status_checked_at = now
    order.save(update_fields=[
        'status', 'raw_provider_status', 'rbxcrate_response',
        'error_message', 'last_status_checked_at', 'updated_at',
    ])


def _update_batch_status(batch: RobuxCrateBatch) -> None:
    """Recompute batch aggregate status from its orders."""
    statuses = list(batch.orders.values_list('status', flat=True))
    if not statuses:
        return

    pending_or_unknown = {RobuxCrateOrder.Status.PENDING, RobuxCrateOrder.Status.UNKNOWN}
    in_progress = {RobuxCrateOrder.Status.QUEUED, RobuxCrateOrder.Status.PROGRESS}

    has_pending = any(s in pending_or_unknown for s in statuses)
    has_in_progress = any(s in in_progress for s in statuses)

    if has_pending or has_in_progress:
        batch.status = RobuxCrateBatch.Status.PROCESSING
    else:
        # All orders are in final states
        success_count = sum(1 for s in statuses if s == RobuxCrateOrder.Status.COMPLETED)
        error_count = sum(1 for s in statuses if s in {RobuxCrateOrder.Status.ERROR, RobuxCrateOrder.Status.CANCELLED})

        if error_count == len(statuses):
            batch.status = RobuxCrateBatch.Status.FAILED
        elif success_count == len(statuses):
            batch.status = RobuxCrateBatch.Status.COMPLETED
        else:
            batch.status = RobuxCrateBatch.Status.PARTIAL

    batch.save(update_fields=['status', 'updated_at'])


# ── Single order refresh (for manual refresh button) ─────────────

def refresh_order_status(order: RobuxCrateOrder) -> bool:
    """Refresh a single order's status from RbxCrate. Returns True on success."""
    try:
        cred = ServiceCredential.objects.get(slug='game-service-rbxcrate', is_active=True)
    except ServiceCredential.DoesNotExist:
        return False

    creds = cred.credentials or {}
    if not creds.get('api_key'):
        return False

    client = RobuxCrateService.build_client(cred)

    try:
        result = client.get_order_info(str(order.id))
    except Exception:
        logger.warning('refresh_order_status failed for %s', order.id)
        return False

    now = timezone.now()
    if result.ok:
        data = result.data or {}
        raw = data.get('status', '')
        mapped = map_provider_status(raw) if raw else order.status
        order.status = mapped
        order.raw_provider_status = raw
        order.rbxcrate_response = data
        order.error_message = data.get('error', '') or ''
    else:
        order.error_message = result.error.message if result.error else 'Refresh failed'

    order.last_status_checked_at = now
    order.save(update_fields=[
        'status', 'raw_provider_status', 'rbxcrate_response',
        'error_message', 'last_status_checked_at', 'updated_at',
    ])

    # Update parent batch status
    _update_batch_status(order.batch)
    return result.ok
