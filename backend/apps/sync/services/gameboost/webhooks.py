"""Idempotent asynchronous processing for signed GameBoost purchase events."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.orders.enums import OrderStatus
from apps.orders.models import Order
from apps.sync.enums import ResourceType
from apps.sync.models import GameBoostWebhookEvent
from apps.sync.orchestrator import _sync_account
from apps.sync.services.cross_platform import reconcile_cross_platform, notify_unlinked_orders
from apps.sync.services.shared.sync_log import log_sync, log_sync_error
from apps.sync.enums import SyncLogLevel

logger = logging.getLogger(__name__)
MAX_WEBHOOK_PROCESS_ATTEMPTS = 3
PROCESSING_LEASE_MINUTES = 15


def _claim_next_event() -> GameBoostWebhookEvent | None:
    with transaction.atomic():
        # A worker crash can leave a durable event in PROCESSING. Requeue only
        # after its bounded lease expires; normal runs remain serialized by the
        # scheduler's max_instances=1 setting and RawPayload upserts are
        # idempotent if a provider fetch must be repeated.
        stale_before = timezone.now() - timedelta(minutes=PROCESSING_LEASE_MINUTES)
        GameBoostWebhookEvent.objects.filter(
            status=GameBoostWebhookEvent.Status.PROCESSING,
            updated_at__lt=stale_before,
            attempts__lt=MAX_WEBHOOK_PROCESS_ATTEMPTS,
        ).update(
            status=GameBoostWebhookEvent.Status.PENDING,
            last_error='processing lease expired; queued for one bounded retry',
            updated_at=timezone.now(),
        )
        event = (
            GameBoostWebhookEvent.objects.select_for_update(skip_locked=True)
            .select_related('integration_account__credential')
            .filter(status=GameBoostWebhookEvent.Status.PENDING)
            .order_by('received_at')
            .first()
        )
        if event is None:
            return None
        event.status = GameBoostWebhookEvent.Status.PROCESSING
        event.attempts += 1
        event.save(update_fields=['status', 'attempts', 'updated_at'])
        return event


def _finish_event(event_id: int, *, status: str, error: str = '') -> None:
    GameBoostWebhookEvent.objects.filter(pk=event_id).update(
        status=status,
        last_error=error[:1000],
        processed_at=timezone.now(),
        updated_at=timezone.now(),
    )


def process_next_gameboost_purchase_event(*, proxy_pool=None) -> bool:
    """Process at most one accepted event through the canonical order service.

    The webhook payload itself is not trusted as order data.  A signed event
    simply prompts a normal provider order sync for that exact store; the
    provider fetch, RawPayload ingestion, status guard, and pool-sale binding
    remain the only authoritative path to local mutations.
    """
    event = _claim_next_event()
    if event is None:
        return False

    account = event.integration_account
    started = timezone.now()
    try:
        run = _sync_account(account, ResourceType.ORDERS, proxy_pool=proxy_pool)
        _sync_account(account, ResourceType.ITEM_ORDERS, proxy_pool=proxy_pool)

        new_order_ids = list(
            Order.objects.filter(
                integration_account=account,
                created_at__gte=started,
            ).exclude(
                status__in=[
                    OrderStatus.CANCELLED,
                    OrderStatus.REFUNDED,
                    OrderStatus.DISPUTED,
                ],
            ).values_list('id', flat=True)
        )
        if new_order_ids:
            reconcile_cross_platform(new_order_ids)
            notify_unlinked_orders(new_order_ids)

        _finish_event(event.pk, status=GameBoostWebhookEvent.Status.COMPLETED)
        log_sync(
            'gameboost_webhook',
            SyncLogLevel.SUCCESS,
            f'{account.slug}: accepted purchase event processed ({len(new_order_ids)} new orders)',
            sync_run=run,
            integration_account=account,
        )
        return True
    except Exception as exc:
        message = str(exc)
        with transaction.atomic():
            current = GameBoostWebhookEvent.objects.select_for_update().get(pk=event.pk)
            if current.attempts < MAX_WEBHOOK_PROCESS_ATTEMPTS:
                current.status = GameBoostWebhookEvent.Status.PENDING
                current.last_error = message[:1000]
                current.save(update_fields=['status', 'last_error', 'updated_at'])
            else:
                _finish_event(
                    current.pk,
                    status=GameBoostWebhookEvent.Status.FAILED,
                    error=message,
                )
        log_sync_error(
            'gameboost_webhook',
            f'{account.slug}: purchase event processing failed: {message}',
            exc=exc,
            integration_account=account,
        )
        return False
