"""
R6Locker high-level facade.

Provides a clean consumer-facing API that coordinates:
- Optional proxy selection
- Delegation to the low-level client

This facade is intentionally thin. The public tracker endpoint is
unauthenticated and read-only, so there is no auth orchestration
or retry policy in this phase. Callers who need retry behavior
can retry externally based on ApiResult.error.is_retryable.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool


class R6LockerFacade:
    """
    High-level R6Locker tracker interface.

    Coordinates proxy selection around the low-level R6LockerClient.
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

    def get_account_data(
        self,
        account_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """
        Fetch public account data from the R6Locker tracker.

        Args:
            account_id: The R6Locker account/profile ID to look up.
            proxy_group: Optional proxy group for request routing.

        Returns:
            ApiResult with the raw account data dict on success.
        """
        proxy_url = self._get_proxy_url(group=proxy_group)
        return self._client.get_account_data(account_id, proxy_url=proxy_url)
