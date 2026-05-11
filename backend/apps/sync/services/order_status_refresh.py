"""Order status refresh — periodic re-fetch of non-final orders.

Problem: Incremental order sync stops at ``is_already_seen``, so orders
whose status changed *after* initial ingestion never get updated.

Solution: Re-fetch orders from the API going backward (newest-first)
until we pass the oldest non-final order's ``sold_at`` timestamp.
Each fetched order is re-ingested via the existing ``_ingest_raw`` +
``parse_and_apply`` path — if the payload hash changed, the order
row is updated with the new status.

Runs hourly via APScheduler.  Eldorado, Gameboost, and PlayerAuctions
have status transitions that need refreshing.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.db.models import Min
from django.utils import timezone

from apps.integrations.models import IntegrationAccount
from apps.integrations.providers.registry import (
    clear_client_cache,
    get_or_build_client,
    get_provider,
)
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.orders.enums import OrderStatus
from apps.orders.models import Order
from apps.sync.enums import ParseStatus, ResourceType, SyncLogLevel, SyncMode
from apps.sync.models import SyncCheckpoint
from apps.sync.services.registry import get_service_class
from apps.sync.services.shared.sync_log import log_sync, log_sync_error

logger = logging.getLogger(__name__)

# Non-final statuses that may still transition
_NON_FINAL_STATUSES = (OrderStatus.PENDING, OrderStatus.DELIVERED)

# Providers that need status refresh
_REFRESH_PROVIDERS = ('eldorado', 'gameboost', 'playerauctions')

# Safety margin — go 1 day further back than the oldest non-final order
_LOOKBACK_MARGIN = timedelta(days=1)


def run_order_status_refresh() -> None:
    """Entry point — called by APScheduler hourly.

    For each provider with non-final orders:
    1. Find the oldest non-final order's sold_at
    2. Re-fetch orders from API (newest→oldest) until that date
    3. Re-ingest + re-parse → status updates happen automatically
    """
    log_sync('order_status_refresh', SyncLogLevel.INFO, 'Status refresh started')
    started = timezone.now()

    clear_client_cache()
    proxy_pool = build_proxy_pool()

    total_updated = 0

    for provider_name in _REFRESH_PROVIDERS:
        try:
            updated = _refresh_provider(provider_name, proxy_pool)
            total_updated += updated
        except Exception as e:
            log_sync_error(
                'order_status_refresh',
                f'{provider_name}: {e}',
                exc=e,
            )

    clear_client_cache()

    elapsed = (timezone.now() - started).total_seconds()
    log_sync(
        'order_status_refresh', SyncLogLevel.SUCCESS,
        f'Status refresh completed in {elapsed:.0f}s — {total_updated} orders re-ingested',
    )


def _refresh_provider(provider_name: str, proxy_pool: Any) -> int:
    """Refresh order statuses for all active accounts of a provider.

    Returns total number of orders re-ingested.
    """
    # Find the oldest non-final order date for this provider
    cutoff_date = _get_oldest_nonfinal_date(provider_name)
    if cutoff_date is None:
        logger.info(
            'order_status_refresh: %s — no non-final orders, skipping',
            provider_name,
        )
        return 0

    # Apply safety margin
    cutoff_date -= _LOOKBACK_MARGIN
    logger.info(
        'order_status_refresh: %s — refreshing back to %s',
        provider_name, cutoff_date.isoformat(),
    )

    accounts = list(
        IntegrationAccount.objects.select_related('credential').filter(
            provider=provider_name,
            is_active=True,
            credential__is_active=True,
        )
    )

    if not accounts:
        return 0

    total = 0
    for account in accounts:
        try:
            count = _refresh_account(account, cutoff_date, proxy_pool)
            total += count
            if count:
                log_sync(
                    'order_status_refresh', SyncLogLevel.SUCCESS,
                    f'{account.slug}: {count} orders re-ingested',
                    integration_account=account,
                )
        except Exception as e:
            log_sync_error(
                'order_status_refresh',
                f'{account.slug}: {e}',
                exc=e,
                integration_account=account,
            )

    return total


def _refresh_account(
    account: IntegrationAccount,
    cutoff_date,
    proxy_pool: Any,
) -> int:
    """Re-fetch orders for one account until cutoff_date.

    Uses the existing sync service's fetch_page + _ingest_raw + parse_and_apply
    to process each order.  Does NOT create a SyncRun — this is a lightweight
    refresh, not a full sync.
    """
    service_class = get_service_class(ResourceType.ORDERS, account.provider)
    if service_class is None:
        return 0

    provider = get_provider(account.provider)
    group_name = get_group_name(account)
    client = get_or_build_client(
        account.provider, account.credential,
        proxy_pool=proxy_pool,
        proxy_group=group_name,
    )
    service = service_class(provider, client)

    # Build a dedicated checkpoint for status refresh (newest-first)
    checkpoint = _build_refresh_checkpoint(account, service)

    count = 0
    pages = 0
    max_pages = 500

    while pages < max_pages:
        items, next_cursor = service.fetch_page(account, checkpoint)
        if not items:
            break

        pages += 1

        passed_cutoff = False
        for item in items:
            # Check if we've gone past the cutoff date
            item_ts = service.extract_remote_timestamp(item)
            if item_ts and item_ts < cutoff_date:
                passed_cutoff = True
                break

            remote_id = service.extract_remote_id(item)
            if not remote_id:
                continue

            # Skip prepare_item (enrichment) — we only care about status changes,
            # credentials are irrelevant here and would cause unnecessary API calls.
            raw = service._ingest_raw(account, remote_id, item)

            # _ingest_raw sets parse_status=PENDING when hash changes,
            # but doesn't call parse. We must trigger parse ourselves.
            if raw.parse_status == ParseStatus.PENDING:
                _try_parse(raw, service)

            count += 1

        # Advance cursor for next page
        if next_cursor and not passed_cutoff:
            checkpoint.cursor = next_cursor
        else:
            break

    logger.info(
        'order_status_refresh: %s — %d orders across %d pages',
        account.slug, count, pages,
    )
    return count


def _try_parse(raw, service) -> None:
    """Parse a PENDING raw payload using the service's parse_and_apply."""
    try:
        # _Counter is a lightweight stand-in for SyncRun (which expects
        # mutable counter attributes but we don't need to persist them).
        class _Counter:
            created_count = 0
            updated_count = 0
            error_count = 0
            processed_count = 0

        service._try_parse(raw, _Counter())
    except Exception:
        logger.debug(
            'order_status_refresh: parse failed for %s',
            raw.remote_id, exc_info=True,
        )


def _build_refresh_checkpoint(account, service) -> SyncCheckpoint:
    """Get or create a dedicated checkpoint for status refresh.

    Uses mode='incremental' with a special resource_type suffix so it
    doesn't interfere with the real incremental sync checkpoint.
    Gameboost's fetch_page calls checkpoint.save() internally, so the
    checkpoint must be a real persisted DB object.
    """
    _REFRESH_RESOURCE = 'orders_refresh'

    checkpoint, _ = SyncCheckpoint.objects.get_or_create(
        integration_account=account,
        resource_type=_REFRESH_RESOURCE,
        mode=SyncMode.INCREMENTAL,
        defaults={'cursor': '', 'meta': {}},
    )

    # Reset cursor each run — always start from newest
    if hasattr(service, 'INCREMENTAL_DIRECTION') and hasattr(service, '_DIRECTION_CONFIG'):
        direction = service.INCREMENTAL_DIRECTION
        cfg = service._DIRECTION_CONFIG[direction]
        checkpoint.cursor = cfg['initial_cursor']
    else:
        # Gameboost uses page numbers — start at page 1
        checkpoint.cursor = ''
        checkpoint.meta = {'_incremental_page': 1}

    checkpoint.save(update_fields=['cursor', 'meta', 'updated_at'])
    return checkpoint


def _get_oldest_nonfinal_date(provider_name: str):
    """Return the sold_at of the oldest non-final order for a provider."""
    result = Order.objects.filter(
        integration_account__provider=provider_name,
        status__in=_NON_FINAL_STATUSES,
    ).aggregate(oldest=Min('sold_at'))
    return result['oldest']
