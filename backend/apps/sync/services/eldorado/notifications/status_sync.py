"""Eldorado notification → order status sync.

Polls /api/notifications/me per active Eldorado account every 10 minutes.
Maps notification events to OrderStatus and updates matching orders via
store_order_id. ActionRequired events are skipped (handled by order sync).

State strategy
--------------
Uses ``SyncCheckpoint(resource_type='notifications', mode='incremental')``
per account.  The ``last_seen_remote_id`` field stores the notification ID
of the most recently processed notification (high water mark).

Poll logic:
  1. Always start from sentinel cursor (newest → oldest).
  2. Walk pages backward until we hit ``last_seen_remote_id``.
  3. Process all notifications newer than the watermark.
  4. Bootstrap (no stored ID): process all unread, save first ID as watermark.
  5. Update ``last_seen_remote_id`` to the newest notification's ID.
"""
from __future__ import annotations

import logging
from typing import Any

from django.utils import timezone

from apps.integrations.models import IntegrationAccount
from apps.integrations.providers.registry import get_or_build_client
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.orders.enums import OrderStatus
from apps.orders.models import Order
from apps.sync.enums import ResourceType, SyncMode
from apps.sync.models import SyncCheckpoint

logger = logging.getLogger(__name__)

_PROVIDER = 'eldorado'

# Sentinel cursor — always start from newest notifications
_CURSOR_TOP = '9999-99-99 99:99:99.999999999999999-9999-9999-9999-999999999999'

# Notification event → OrderStatus map.
# ActionRequired events are absent — they are skipped at the type check.
_EVENT_STATUS_MAP: dict[str, str] = {
    'OrderDelivered': OrderStatus.DELIVERED,
    'OrderCancelledBySeller': OrderStatus.CANCELLED,
    'OrderDisputed': OrderStatus.DISPUTED,
    'OrderCancelledByAdminAfterDispute': OrderStatus.CANCELLED,
    'OrderReceivedByAdminAfterDispute': OrderStatus.DISPUTE_RESOLVED,
    'OrderReceivedByBuyerAfterDispute': OrderStatus.COMPLETED,
}


class EldoradoNotificationStatusSync:
    """Poll Eldorado unread notifications and update matching order statuses."""

    def run(self) -> None:
        """Iterate all active Eldorado accounts and sync notification statuses."""
        accounts = list(
            IntegrationAccount.objects.select_related('credential').filter(
                provider=_PROVIDER,
                is_active=True,
                credential__is_active=True,
            )
        )
        if not accounts:
            logger.debug('eldorado_notif_sync: no active Eldorado accounts')
            return

        proxy_pool = build_proxy_pool()

        for account in accounts:
            try:
                self._sync_account(account, proxy_pool)
            except Exception:
                logger.exception(
                    'eldorado_notif_sync: unhandled error for account %s',
                    account.name,
                )

    def _sync_account(
        self,
        account: IntegrationAccount,
        proxy_pool: Any,
    ) -> None:
        checkpoint, _ = SyncCheckpoint.objects.get_or_create(
            integration_account=account,
            resource_type=ResourceType.NOTIFICATIONS,
            mode=SyncMode.INCREMENTAL,
            defaults={'last_seen_remote_id': '', 'cursor': ''},
        )

        facade = get_or_build_client(
            _PROVIDER,
            account.credential,
            proxy_pool=proxy_pool,
            proxy_group=get_group_name(account),
        )

        last_seen_id = checkpoint.last_seen_remote_id
        updated = 0
        skipped = 0
        # Collect all new notifications across pages before processing
        new_notifications: list = []
        most_recent_id: str | None = None
        hit_watermark = False

        cursor = _CURSOR_TOP

        while not hit_watermark:
            result = facade.get_notifications(
                params={
                    'cursorValue': cursor,
                    'pageDirection': 'Next',
                    'notificationReadStatuses': 'IsUnread',
                }
            )

            if not result.ok:
                logger.warning(
                    'eldorado_notif_sync: API error for %s: %s',
                    account.name, result.error,
                )
                break

            page = result.data

            if not page.results:
                break

            for item in page.results:
                notif = item.notification

                # Save the very first (most recent) notification ID
                if most_recent_id is None:
                    most_recent_id = notif.id

                # Hit the watermark — stop collecting
                if last_seen_id and notif.id == last_seen_id:
                    hit_watermark = True
                    break

                new_notifications.append(item)

            # No more pages
            if not page.nextPageCursor:
                break

            cursor = page.nextPageCursor

        # Bootstrap — first run, just save the watermark
        if not last_seen_id and most_recent_id:
            checkpoint.last_seen_remote_id = most_recent_id
            checkpoint.last_run_at = timezone.now()
            checkpoint.save(update_fields=[
                'last_seen_remote_id', 'last_run_at', 'updated_at',
            ])
            logger.info(
                'eldorado_notif_sync: bootstrap for %s — watermark set to %s (%d notifications)',
                account.name, most_recent_id, len(new_notifications),
            )
            return

        # Process collected notifications
        for item in new_notifications:
            notif = item.notification

            # ActionRequired events are handled by order sync — skip
            if notif.type == 'ActionRequired':
                skipped += 1
                continue

            new_status = _EVENT_STATUS_MAP.get(notif.event)
            if new_status is None:
                logger.warning(
                    'eldorado_notif_sync: unknown event=%s id=%s — skipping',
                    notif.event, notif.id,
                )
                skipped += 1
                continue

            details_id = notif.details.detailsId
            if not details_id:
                logger.warning(
                    'eldorado_notif_sync: notification id=%s has no detailsId — skipping',
                    notif.id,
                )
                skipped += 1
                continue

            rows = Order.objects.filter(
                store_order_id=details_id,
                integration_account__provider=_PROVIDER,
            ).update(status=new_status)

            if rows == 0:
                logger.warning(
                    'eldorado_notif_sync: no order found for detailsId=%s event=%s — skipping',
                    details_id, notif.event,
                )
                skipped += 1
            else:
                updated += rows

        # Advance watermark
        if most_recent_id:
            checkpoint.last_seen_remote_id = most_recent_id
            checkpoint.last_run_at = timezone.now()
            checkpoint.save(update_fields=[
                'last_seen_remote_id', 'last_run_at', 'updated_at',
            ])

        logger.info(
            'eldorado_notif_sync: %s done — updated=%d skipped=%d new=%d',
            account.name, updated, skipped, len(new_notifications),
        )
