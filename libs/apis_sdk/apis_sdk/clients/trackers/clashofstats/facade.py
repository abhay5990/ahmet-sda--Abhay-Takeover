"""
ClashOfStats high-level facade.

Provides a clean consumer-facing API that coordinates:
- Optional proxy selection
- Delegation to the low-level client

The public player endpoint is unauthenticated and read-only.
The parallel proxy/no-proxy race condition strategy from the legacy
client is app-level orchestration — not part of this SDK facade.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool


class ClashOfStatsFacade:
    """
    High-level ClashOfStats tracker interface.

    Coordinates proxy selection around the low-level ClashOfStatsClient.
    No auth or retry orchestration — the public tracker is unauthenticated
    and retry is left to the caller.
    """

    def __init__(
        self,
        client: Any,
        *,
        proxy_pool: ProxyPool | None = None,
        logger: SdkLogger | None = None,
    ) -> None:
        self._client = client
        self._proxy_pool = proxy_pool
        self._logger = logger or NullLogger()

    # ---------------------------------------------------------------------------
    # Proxy helpers
    # ---------------------------------------------------------------------------

    def _get_proxy_url(self, *, group: str | None = None) -> str | None:
        """Acquire a proxy URL from the pool, if available."""
        if self._proxy_pool is None:
            return None
        proxy = self._proxy_pool.acquire(group=group)
        if proxy is None:
            return None
        return proxy.to_url()

    # ---------------------------------------------------------------------------
    # Public tracker
    # ---------------------------------------------------------------------------

    def get_player_data(
        self,
        player_tag: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """
        Fetch player data from ClashOfStats.

        Args:
            player_tag: CoC player tag (e.g. 'QCR88LYGP', without '#').
            proxy_group: Optional proxy group for request routing.

        Returns:
            ApiResult with the raw player data dict on success.
        """
        proxy_url = self._get_proxy_url(group=proxy_group)
        return self._client.get_player_data(player_tag, proxy_url=proxy_url)
