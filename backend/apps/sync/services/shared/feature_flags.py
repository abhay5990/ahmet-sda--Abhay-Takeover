"""Sync feature flag helpers.

Usage::

    from apps.sync.services.shared.feature_flags import is_sync_feature_enabled, SyncFlag

    if not is_sync_feature_enabled(SyncFlag.RECONCILE):
        logger.info('Cross-platform reconciliation disabled, skipping')
        return
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SyncFlag:
    """Known flag keys — keeps strings in one place."""

    LZT = 'sync.lzt'
    OFFERS = 'sync.offers'
    ORDERS = 'sync.orders'
    RECONCILE = 'sync.reconcile'
    UNLINKED_NOTIFY = 'sync.unlinked_notify'
    ELDORADO_NOTIFICATIONS = 'sync.eldorado_notifications'
    REVIEW_MONITOR = 'sync.review_monitor'
    ORDER_STATUS_REFRESH = 'sync.order_status_refresh'
    POOL_SWEEP = 'sync.pool_sweep'
    PAUSE_EXPIRING = 'sync.pause_expiring'


def is_sync_feature_enabled(key: str, *, default: bool = True) -> bool:
    """Check if a sync feature flag is enabled.

    Reads from DB on every call (single indexed lookup, negligible cost
    at sync-chain frequency).  Returns ``default`` if the key doesn't
    exist in the DB — safe for first deploy before data migration runs.
    """
    from apps.sync.models import SyncFeatureFlag

    try:
        flag = SyncFeatureFlag.objects.filter(key=key).only('is_enabled').first()
        if flag is None:
            return default
        return flag.is_enabled
    except Exception:
        # DB not ready (migration pending, etc.) — fail open
        logger.debug('SyncFeatureFlag lookup failed for %s, using default=%s', key, default)
        return default
