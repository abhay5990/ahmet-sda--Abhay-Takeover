"""Bounded processing for signed U7Buy seller webhooks."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.integrations.providers.registry import get_or_build_client
from apps.orders.enums import OrderStatus
from apps.orders.models import Order
from apps.sync.models import U7BuyWebhookEvent
from apps.sync.services.cross_platform import reconcile_cross_platform, notify_unlinked_orders
from apps.sync.services.shared.sync_log import log_sync, log_sync_error
from apps.sync.enums import SyncLogLevel
from .orders.service import U7BuyOrderSyncService

logger = logging.getLogger(__name__)
MAX_WEBHOOK_PROCESS_ATTEMPTS = 3
PROCESSING_LEASE_MINUTES = 15


def _claim_next_event() -> U7BuyWebhookEvent | None:
    with transaction.atomic():
        stale_before = timezone.now() - timedelta(minutes=PROCESSING_LEASE_MINUTES)
        U7BuyWebhookEvent.objects.filter(
            status=U7BuyWebhookEvent.Status.PROCESSING,
            updated_at__lt=stale_before,
            attempts__lt=MAX_WEBHOOK_PROCESS_ATTEMPTS,
        ).update(
            status=U7BuyWebhookEvent.Status.PENDING,
            last_error="processing lease expired; queued for one bounded retry",
            updated_at=timezone.now(),
        )
        event = (
            U7BuyWebhookEvent.objects.select_for_update(skip_locked=True)
            .select_related("integration_account__credential")
            .filter(status=U7BuyWebhookEvent.Status.PENDING)
            .order_by("received_at")
            .first()
        )
        if event is None:
            return None
        event.status = U7BuyWebhookEvent.Status.PROCESSING
        event.attempts += 1
        event.save(update_fields=["status", "attempts", "updated_at"])
        return event


def _finish(event_id: int, *, status: str, error: str = "") -> None:
    U7BuyWebhookEvent.objects.filter(pk=event_id).update(
        status=status,
        last_error=error[:1000],
        processed_at=timezone.now(),
        updated_at=timezone.now(),
    )


def process_next_u7buy_webhook_event() -> bool:
    """Read and apply at most one queued U7Buy order event.

    Webhook fields never drive a sale directly: this worker fetches the exact
    order by ID and then uses the normal RawPayload/order/pool path.  It does
    not deliver credentials or complete a U7Buy order; every U7Buy account
    remains manual delivery.
    """
    event = _claim_next_event()
    if event is None:
        return False
    account = event.integration_account
    try:
        if not event.external_order_id:
            _finish(event.pk, status=U7BuyWebhookEvent.Status.COMPLETED)
            return True
        client = get_or_build_client("u7buy", account.credential)
        service = U7BuyOrderSyncService(client=client)
        before_ids = set(
            Order.objects.filter(
                integration_account=account,
                store_order_id=event.external_order_id,
            ).values_list("id", flat=True)
        )
        outcome = service.recover_order_by_id(account, event.external_order_id)
        after_ids = list(
            Order.objects.filter(
                integration_account=account,
                store_order_id=event.external_order_id,
            ).exclude(status__in=[OrderStatus.CANCELLED, OrderStatus.REFUNDED]).values_list("id", flat=True)
        )
        new_ids = [order_id for order_id in after_ids if order_id not in before_ids]
        if new_ids:
            reconcile_cross_platform(new_ids)
            notify_unlinked_orders(new_ids)
        _finish(event.pk, status=U7BuyWebhookEvent.Status.COMPLETED)
        log_sync(
            "u7buy_webhook",
            SyncLogLevel.SUCCESS,
            f"{account.slug}: U7Buy signed event processed ({outcome})",
            integration_account=account,
        )
        return True
    except Exception as exc:
        message = str(exc)
        with transaction.atomic():
            current = U7BuyWebhookEvent.objects.select_for_update().get(pk=event.pk)
            if current.attempts < MAX_WEBHOOK_PROCESS_ATTEMPTS:
                current.status = U7BuyWebhookEvent.Status.PENDING
                current.last_error = message[:1000]
                current.save(update_fields=["status", "last_error", "updated_at"])
            else:
                _finish(current.pk, status=U7BuyWebhookEvent.Status.FAILED, error=message)
        log_sync_error(
            "u7buy_webhook",
            f"{account.slug}: signed event processing failed: {message}",
            exc=exc,
            integration_account=account,
        )
        return False
