"""
R6Locker high-level facade.

Provides a clean consumer-facing API that coordinates:
- Cloudflare cookie resolution (via CfCookieProvider)
- Optional proxy selection
- Automatic retry on 403 (cookie expired)
- Delegation to the low-level client
"""

from __future__ import annotations

import logging
from typing import Any

from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool

logger = logging.getLogger(__name__)


class R6LockerFacade:
    """
    High-level R6Locker tracker interface.

    Coordinates Cloudflare cookie resolution and proxy selection
    around the low-level R6LockerClient.
    """

    def __init__(
        self,
        client: Any,
        *,
        proxy_pool: ProxyPool | None = None,
        cf_cookie_provider: Any | None = None,
        sdk_logger: SdkLogger | None = None,
    ) -> None:
        self._client = client
        self._proxy_pool = proxy_pool
        self._cf_cookie_provider = cf_cookie_provider
        self._logger = sdk_logger or NullLogger()

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
    # Cloudflare cookie helpers
    # ---------------------------------------------------------------------------

    def _get_cf_headers(self) -> dict[str, str]:
        """Get Cookie + User-Agent headers from CfCookieProvider."""
        if self._cf_cookie_provider is None:
            return {}
        cookies = self._cf_cookie_provider.get_cookies()
        if cookies is None:
            return {}
        headers: dict[str, str] = {
            "Cookie": cookies.to_cookie_header(),
        }
        if cookies.user_agent:
            headers["User-Agent"] = cookies.user_agent
        return headers

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

        If a CfCookieProvider is configured, injects cf_clearance cookies.
        On 403, invalidates the cookie and retries once.

        Args:
            account_id: The R6Locker account/profile ID to look up.
            proxy_group: Optional proxy group for request routing.

        Returns:
            ApiResult with the raw account data dict on success.
        """
        proxy_url = self._get_proxy_url(group=proxy_group)
        cf_headers = self._get_cf_headers()

        result = self._client.get_account_data(
            account_id, proxy_url=proxy_url, extra_headers=cf_headers,
        )

        # On 403 with cookie provider: invalidate and retry once
        if (
            not result.ok
            and result.status_code == 403
            and self._cf_cookie_provider is not None
        ):
            logger.info("R6Locker 403 — invalidating cf_clearance and retrying")
            self._cf_cookie_provider.invalidate()
            cf_headers = self._get_cf_headers()
            if cf_headers:
                result = self._client.get_account_data(
                    account_id, proxy_url=proxy_url, extra_headers=cf_headers,
                )

        return result
