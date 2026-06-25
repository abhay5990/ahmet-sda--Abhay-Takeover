"""Background batch processor for RobuxCrate orders.

Called periodically by APScheduler (runapscheduler command).
Picks up batches whose orders are still in non-final states and sends them
to the RbxCrate API using each batch's assigned merchant credential.

Auto-delivery: when at least one order in a batch reaches COMPLETED,
a delivery request is sent to the marketplace (e.g. Eldorado PUT deliver).
"""
from __future__ import annotations

import logging

from django.utils import timezone

from apis_sdk.core.enums import ErrorCategory
from apps.integrations.services.robuxcrate import RobuxCrateService
from apps.tools.models import RobuxCrateBatch, RobuxCrateOrder

logger = logging.getLogger(__name__)

# Provider status → internal status mapping
_STATUS_MAP: dict[str, str] = {
    'queued': RobuxCrateOrder.Status.QUEUED,
    'in_progress': RobuxCrateOrder.Status.QUEUED,
    'inprogress': RobuxCrateOrder.Status.QUEUED,
    'completed': RobuxCrateOrder.Status.COMPLETED,
    'done': RobuxCrateOrder.Status.COMPLETED,
    'error': RobuxCrateOrder.Status.ERROR,
    'failed': RobuxCrateOrder.Status.ERROR,
    'cancelled': RobuxCrateOrder.Status.CANCELLED,
    'canceled': RobuxCrateOrder.Status.CANCELLED,
}


def map_provider_status(raw: str) -> str:
    """Map a raw provider status string to an internal Status value."""
    return _STATUS_MAP.get(raw.lower().strip(), RobuxCrateOrder.Status.UNKNOWN)


_UNCERTAIN_CATEGORIES = frozenset({
    ErrorCategory.NETWORK,
    ErrorCategory.TIMEOUT,
    ErrorCategory.UNKNOWN,
    ErrorCategory.SERVER_ERROR,
})


def _is_uncertain_error(result) -> bool:
    if not result.error:
        return False
    return result.error.category in _UNCERTAIN_CATEGORIES


# ── Public entry point (called by APScheduler) ───────────────────

_NON_FINAL_BATCH_STATUSES = [
    RobuxCrateBatch.Status.PENDING,
    RobuxCrateBatch.Status.QUEUED,
    RobuxCrateBatch.Status.PROCESSING,
]


def process_pending_batches() -> None:
    """Find batches with unprocessed orders and send them to RbxCrate.

    Each batch uses its own merchant (ServiceCredential FK) for API calls.
    """
    batches = list(
        RobuxCrateBatch.objects
        .filter(status__in=_NON_FINAL_BATCH_STATUSES)
        .select_related('merchant', 'marketplace_store')
        [:50]
    )
    if not batches:
        return

    # Cache clients per merchant to avoid rebuilding
    merchant_clients: dict[int, object] = {}

    for batch in batches:
        try:
            client = _get_merchant_client(batch, merchant_clients)
            if client is None:
                continue
            _process_batch(batch, client)
        except Exception:
            logger.exception('Unexpected error processing batch %s', batch.id)


def _get_merchant_client(batch: RobuxCrateBatch, cache: dict) -> object | None:
    """Resolve RbxCrate client from batch.merchant FK, with caching."""
    if not batch.merchant_id:
        logger.error('Batch %s has no merchant assigned — skipping', batch.id)
        return None

    if batch.merchant_id in cache:
        return cache[batch.merchant_id]

    cred = batch.merchant
    if not cred.is_active:
        logger.error('Merchant %s is inactive — skipping batch %s', cred.slug, batch.id)
        return None

    creds = cred.credentials or {}
    if not creds.get('api_key'):
        logger.error('Merchant %s has no api_key — skipping batch %s', cred.slug, batch.id)
        return None

    client = RobuxCrateService.build_client(cred)
    cache[batch.merchant_id] = client
    return client


def _process_batch(batch: RobuxCrateBatch, client) -> None:
    """Process a single batch: send pending orders, reconcile unknowns,
    update aggregate status, and trigger auto-delivery if applicable."""
    # Mark as processing
    if batch.status in (RobuxCrateBatch.Status.PENDING, RobuxCrateBatch.Status.QUEUED):
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

    # 3) Check non-final orders for status updates
    in_progress = list(batch.orders.filter(
        status=RobuxCrateOrder.Status.QUEUED,
    ))
    for order in in_progress:
        _check_order_status(order, client)

    # 4) Update batch aggregate status + trigger auto-delivery
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
        logger.warning(
            'Uncertain error sending order %s (category=%s) — marking UNKNOWN',
            order.id, result.error.category if result.error else '?',
        )
        order.status = RobuxCrateOrder.Status.UNKNOWN
        order.error_message = f'Uncertain: {result.error.message}' if result.error else 'Status uncertain'
        order.rbxcrate_response = (result.error.details if result.error else None) or {}
    else:
        order.status = RobuxCrateOrder.Status.ERROR
        order.error_message = result.error.message if result.error else 'Unknown provider error'
        order.rbxcrate_response = (result.error.details if result.error else None) or {}

    order.last_status_checked_at = now
    order.save(update_fields=[
        'status', 'raw_provider_status', 'rbxcrate_response',
        'error_message', 'last_status_checked_at', 'updated_at',
    ])


def _check_order_status(order: RobuxCrateOrder, client) -> None:
    """Poll RbxCrate for the latest status of a queued/in-progress order."""
    try:
        result = client.get_order_info(str(order.id))
    except Exception:
        logger.warning('Status check failed for order %s', order.id)
        return

    now = timezone.now()
    if result.ok:
        data = result.data or {}
        raw = data.get('status', '')
        order.status = map_provider_status(raw) if raw else order.status
        order.raw_provider_status = raw
        order.rbxcrate_response = data
        order.error_message = data.get('error', '') or ''
    # On failure, leave current status — will retry next cycle

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
        logger.warning('Reconciliation uncertain for order %s — still UNKNOWN', order.id)
        return
    else:
        order.status = RobuxCrateOrder.Status.ERROR
        order.error_message = 'Order not found at provider after network error'

    order.last_status_checked_at = now
    order.save(update_fields=[
        'status', 'raw_provider_status', 'rbxcrate_response',
        'error_message', 'last_status_checked_at', 'updated_at',
    ])


def _update_batch_status(batch: RobuxCrateBatch) -> None:
    """Recompute batch aggregate status from its orders.

    Auto-delivery: at least 1 order completed → attempt marketplace delivery.
    On success → COMPLETED.  On failure → stay PROCESSING so scheduler retries.
    """
    statuses = list(batch.orders.values_list('status', flat=True))
    if not statuses:
        return

    success_count = sum(1 for s in statuses if s == RobuxCrateOrder.Status.COMPLETED)
    non_final = [s for s in statuses if s not in RobuxCrateOrder.FINAL_STATUSES]

    # All orders failed/cancelled — nothing to deliver
    if not non_final and success_count == 0:
        batch.status = RobuxCrateBatch.Status.ERROR
        batch.delivery_error = ''
        batch.save(update_fields=['status', 'delivery_error', 'updated_at'])
        return

    # At least 1 completed → attempt delivery (or retry if previous attempt failed)
    if success_count > 0 and batch.status != RobuxCrateBatch.Status.COMPLETED:
        _attempt_delivery(batch, success_count, len(statuses))
        return

    # No completed orders yet, still processing
    if non_final:
        batch.status = RobuxCrateBatch.Status.PROCESSING
        batch.save(update_fields=['status', 'updated_at'])


def _attempt_delivery(batch: RobuxCrateBatch, success_count: int, total: int) -> None:
    """Attempt to deliver the marketplace order.

    Success → COMPLETED.  Failure → stay PROCESSING (scheduler retries next cycle).
    """
    if batch.marketplace == RobuxCrateBatch.Marketplace.ELDORADO:
        ok, error = _deliver_eldorado(batch)
    else:
        ok = False
        error = f'Marketplace {batch.marketplace} delivery not yet implemented'

    now = timezone.now()
    batch.delivery_attempted_at = now

    if ok:
        batch.status = RobuxCrateBatch.Status.COMPLETED
        batch.delivery_error = ''
        logger.info(
            'Batch %s delivered (%d/%d orders completed)',
            batch.id, success_count, total,
        )
    else:
        # Stay PROCESSING so scheduler picks it up again
        batch.status = RobuxCrateBatch.Status.PROCESSING
        batch.delivery_error = error or 'Delivery failed'
        logger.warning(
            'Batch %s delivery failed (%d/%d completed): %s — will retry',
            batch.id, success_count, total, error,
        )

    batch.save(update_fields=[
        'status', 'delivery_attempted_at', 'delivery_error', 'updated_at',
    ])


def _deliver_eldorado(batch: RobuxCrateBatch) -> tuple[bool, str]:
    """Send PUT deliver request to Eldorado for the batch's marketplace order."""
    store_cred = batch.marketplace_store
    if not store_cred:
        return False, 'No marketplace store credential assigned'

    try:
        from apps.integrations.providers.eldorado import EldoradoProvider
        provider = EldoradoProvider()
        client = provider.build_client(store_cred)
    except Exception as exc:
        return False, f'Failed to build Eldorado client: {exc}'

    try:
        result = client.deliver_order(batch.marketplace_order_id)
    except Exception as exc:
        return False, f'Unexpected error calling deliver: {exc}'

    if result.ok:
        return True, ''

    error_msg = result.error.message if result.error else 'Unknown error'
    return False, error_msg


# ── Cancel order ──────────────────────────────────────────────────

def cancel_order(order: RobuxCrateOrder) -> tuple[bool, str]:
    """Cancel a single order via RbxCrate API.

    Only non-final orders can be cancelled. Returns (success, error_message).
    """
    if order.status in RobuxCrateOrder.FINAL_STATUSES:
        return False, f'Order is already in final state: {order.status}'

    batch = order.batch
    if not batch.merchant_id:
        return False, 'No merchant assigned to batch'

    cred = batch.merchant
    if not cred.is_active:
        return False, 'Merchant credential is inactive'

    creds = cred.credentials or {}
    if not creds.get('api_key'):
        return False, 'Merchant has no API key'

    client = RobuxCrateService.build_client(cred)

    try:
        result = client.cancel_order(str(order.id))
    except Exception:
        logger.warning('cancel_order failed for %s', order.id)
        return False, 'Unexpected error calling cancel API'

    if result.ok:
        order.status = RobuxCrateOrder.Status.CANCELLED
        order.error_message = ''
        order.last_status_checked_at = timezone.now()
        order.save(update_fields=['status', 'error_message', 'last_status_checked_at', 'updated_at'])
        _update_batch_status(batch)
        return True, ''

    error_msg = result.error.message if result.error else 'Cancel failed'
    return False, error_msg


# ── Single order refresh (for manual refresh button) ─────────────

def refresh_order_status(order: RobuxCrateOrder) -> bool:
    """Refresh a single order's status from RbxCrate.

    Uses the batch's merchant credential. Returns True on success.
    """
    batch = order.batch
    if not batch.merchant_id:
        return False

    cred = batch.merchant
    if not cred.is_active:
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

    # Update parent batch status (may trigger delivery)
    _update_batch_status(order.batch)
    return result.ok
