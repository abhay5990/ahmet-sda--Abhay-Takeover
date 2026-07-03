"""
R6Locker high-level facade.

Coordinates, around the low-level client:
- Cloudflare cookie resolution via CfCookieProvider (nodriver solve).
- Exit-IP pinning: the curl request is routed through the SAME sticky proxy the
  cf_clearance was minted on (cookies.proxy_url) — Cloudflare binds the cookie
  to the exit IP, so browser and curl must share it.
- An escalation ladder on failure:
    403 -> re-solve on same IP -> still 403 -> rotate IP + re-solve.
    429 -> back off + retry -> persistent -> rotate IP + re-solve.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool

logger = logging.getLogger(__name__)


class R6LockerFacade:
    """High-level R6Locker tracker interface with Cloudflare + IP handling."""

    def __init__(
        self,
        client: Any,
        *,
        base_url: str = "https://r6skins.locker",
        proxy_pool: ProxyPool | None = None,
        cf_cookie_provider: Any | None = None,
        sdk_logger: SdkLogger | None = None,
        rate_limit_retries: int = 2,
        backoff_base: float = 5.0,
        backoff_jitter: float = 2.0,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._proxy_pool = proxy_pool
        self._cf_cookie_provider = cf_cookie_provider
        self._logger = sdk_logger or NullLogger()
        self._rate_limit_retries = max(0, rate_limit_retries)
        self._backoff_base = backoff_base
        self._backoff_jitter = backoff_jitter

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

        With a CfCookieProvider configured, injects cf_clearance + connect.sid
        and pins the request to the cookie's exit IP, escalating through
        re-solve / IP rotation on 403 / 429.
        """
        if self._cf_cookie_provider is None:
            # Legacy path: proxy pool, no Cloudflare cookies.
            proxy_url = self._get_proxy_url(group=proxy_group)
            return self._client.get_account_data(account_id, proxy_url=proxy_url)

        result = self._fetch_with_cookies(account_id)
        if result.ok:
            return result

        status = result.status_code

        # --- 403: cf_clearance expired or exit IP flagged ---
        if status == 403:
            logger.info("R6Locker 403 — re-solving cf_clearance on same IP")
            self._cf_cookie_provider.invalidate()
            result = self._fetch_with_cookies(account_id)
            if result.ok or result.status_code != 403:
                return result
            logger.info("R6Locker still 403 — rotating exit IP and re-solving")
            self._cf_cookie_provider.rotate()
            return self._fetch_with_cookies(account_id)

        # --- 429: rate limited ---
        if status == 429:
            return self._handle_rate_limit(account_id, result)

        return result

    # ---------------------------------------------------------------------------
    # Internals
    # ---------------------------------------------------------------------------

    def _fetch_with_cookies(self, account_id: str) -> ApiResult[dict[str, Any]]:
        """One fetch through the cookie's pinned exit IP.

        Solves (if needed) on the profile of the account being fetched — no
        fixed seed profile to maintain.
        """
        solve_url = f"{self._base_url}/profile/{account_id}"
        cookies = self._cf_cookie_provider.get_cookies(solve_url=solve_url)
        if cookies is None:
            return ApiResult.from_error(
                ErrorCategory.AUTHENTICATION,
                "cf_clearance unavailable (Cloudflare solve failed)",
                provider="r6locker",
                is_retryable=True,
            )

        headers = {"Cookie": cookies.to_cookie_header()}
        if cookies.user_agent:
            headers["User-Agent"] = cookies.user_agent

        result = self._client.get_account_data(
            account_id, proxy_url=cookies.proxy_url, extra_headers=headers,
        )
        if result.ok:
            # Count only served requests toward the rotation budget.
            self._cf_cookie_provider.note_use()
        return result

    def _handle_rate_limit(
        self, account_id: str, result: ApiResult[dict[str, Any]]
    ) -> ApiResult[dict[str, Any]]:
        """Back off and retry on 429; rotate the exit IP if it persists."""
        for attempt in range(self._rate_limit_retries):
            delay = self._retry_delay(result, attempt)
            logger.info(
                "R6Locker 429 — backing off %.1fs (retry %d/%d)",
                delay, attempt + 1, self._rate_limit_retries,
            )
            time.sleep(delay)
            result = self._fetch_with_cookies(account_id)
            if result.ok or result.status_code != 429:
                return result

        logger.info("R6Locker persistent 429 — rotating exit IP and re-solving")
        self._cf_cookie_provider.rotate()
        return self._fetch_with_cookies(account_id)

    def _retry_delay(self, result: ApiResult[Any], attempt: int) -> float:
        """Retry-After if provided, else exponential backoff, plus jitter."""
        retry_after = result.error.retry_after if result.error else None
        if retry_after:
            base = float(retry_after)
        else:
            base = self._backoff_base * (2 ** attempt)
        return base + random.uniform(0, self._backoff_jitter)

    def _get_proxy_url(self, *, group: str | None = None) -> str | None:
        """Acquire a proxy URL from the pool (legacy path only)."""
        if self._proxy_pool is None:
            return None
        proxy = self._proxy_pool.acquire(group=group)
        return proxy.to_url() if proxy is not None else None
