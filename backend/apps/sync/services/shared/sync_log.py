"""Convenience helper for writing SyncLog entries."""

from __future__ import annotations

import logging
import traceback
from typing import TYPE_CHECKING

from apps.sync.enums import SyncLogLevel
from apps.sync.models import SyncLog

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationAccount
    from apps.inventory.models import OwnedProduct
    from apps.listings.models import Listing
    from apps.orders.models import Order
    from apps.sync.models import SyncRun

logger = logging.getLogger(__name__)


def log_sync(
    task_name: str,
    level: str,
    message: str,
    *,
    detail: dict | None = None,
    integration_account: 'IntegrationAccount | None' = None,
    order: 'Order | None' = None,
    listing: 'Listing | None' = None,
    owned_product: 'OwnedProduct | None' = None,
    sync_run: 'SyncRun | None' = None,
) -> SyncLog:
    """Create a SyncLog entry and mirror to Python logging."""
    log_level = {
        SyncLogLevel.INFO: logging.INFO,
        SyncLogLevel.SUCCESS: logging.INFO,
        SyncLogLevel.WARNING: logging.WARNING,
        SyncLogLevel.ERROR: logging.ERROR,
    }.get(level, logging.INFO)

    logger.log(log_level, "[%s] %s", task_name, message)

    return SyncLog.objects.create(
        task_name=task_name,
        level=level,
        message=message,
        detail=detail or {},
        integration_account=integration_account,
        order=order,
        listing=listing,
        owned_product=owned_product,
        sync_run=sync_run,
    )


def log_sync_error(
    task_name: str,
    message: str,
    exc: Exception | None = None,
    **kwargs,
) -> SyncLog:
    """Log an error with optional traceback in detail."""
    detail = kwargs.pop('detail', {}) or {}
    if exc:
        detail['error'] = str(exc)
        detail['traceback'] = traceback.format_exc()
    return log_sync(
        task_name,
        SyncLogLevel.ERROR,
        message,
        detail=detail,
        **kwargs,
    )
