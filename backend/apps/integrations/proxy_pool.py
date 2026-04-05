"""Bridge between Django Proxy model and SDK ProxyPool.

Called once at sync chain start to load all active proxies from DB
into an SDK ProxyPool instance. Group name from AccountGroup is used
as the ProxyRecord.group field for pool.acquire(group=...) filtering.
"""
from __future__ import annotations

import logging

from apis_sdk.core.models import ProxyRecord
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.infrastructure.proxy.rotation import RoundRobinRotation

logger = logging.getLogger(__name__)


def build_proxy_pool() -> ProxyPool | None:
    """Load active proxies from DB into a ProxyPool.

    Returns None if no active proxies exist (backward compatible).
    """
    from apps.integrations.models import Proxy

    proxies = Proxy.objects.filter(
        is_active=True,
        group__isnull=False,
    ).select_related('group')

    if not proxies.exists():
        return None

    pool = ProxyPool(strategy=RoundRobinRotation())
    count = 0
    for p in proxies:
        record = ProxyRecord(
            host=p.host,
            port=p.port,
            username=p.username or None,
            password=p.password or None,
            group=p.group.name,
        )
        pool.add(record)
        count += 1

    logger.info("ProxyPool loaded: %d proxies from DB", count)
    return pool


def get_group_name(account) -> str | None:
    """Return the AccountGroup name for an IntegrationAccount, or None."""
    if account.group_id:
        return account.group.name
    return None
