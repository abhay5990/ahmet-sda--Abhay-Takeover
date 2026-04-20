"""
LZT Market high-level facade.

Provides a clean consumer-facing API that coordinates:
- Authentication (Bearer token, externally managed)
- Optional proxy selection
- Retry policy execution with strategy-driven actions
- Instance-level rate limiting (0.2s default between requests)

Lifecycle:
    Facade instances are intended to be long-lived (one per worker/process
    per store account). The transport, auth provider, and proxy pool are
    injected at construction and reused across all calls.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.auth.base import BaseAuthProvider
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.infrastructure.retry.policy import RetryPolicy
from apis_sdk.infrastructure.retry.strategy import RetryStrategy
from apis_sdk.clients.marketplaces._facade_support import FacadeExecutor
from apis_sdk.clients.marketplaces.lzt.models import (
    LztCheckAccountResult,
    LztListingPage,
    LztOrderPage,
    LztPurchaseResult,
)


class LztApiClient(Protocol):
    """Protocol for the low-level LZT client."""

    def get_listings(
        self,
        category: str,
        *,
        params: dict[str, Any] | None = None,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[LztListingPage]: ...

    def get_item(
        self,
        item_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]: ...

    def get_user_orders(
        self,
        *,
        params: dict[str, Any] | None = None,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[LztOrderPage]: ...

    def get_user_items(
        self,
        *,
        params: dict[str, Any] | None = None,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[LztOrderPage]: ...

    def check_account(
        self,
        item_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[LztCheckAccountResult]: ...

    def get_email_letters(
        self,
        *,
        email_password: str,
        limit: int,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]: ...

    def confirm_buy(
        self,
        item_id: str,
        price: float,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[LztPurchaseResult]: ...


class LztFacade:
    """
    High-level LZT Market interface.

    Coordinates authentication, proxy rotation, rate limiting, and
    retry logic around the low-level LztClient.
    """

    def __init__(
        self,
        client: LztApiClient,
        auth: BaseAuthProvider,
        *,
        transport: BaseHttpTransport | None = None,
        proxy_pool: ProxyPool | None = None,
        retry_policy: RetryPolicy | None = None,
        retry_strategy: RetryStrategy | None = None,
        max_retry_attempts: int = 3,
        rate_limit_delay: float = 0.2,
        logger: SdkLogger | None = None,
    ) -> None:
        self._client = client
        self._rate_limit_delay = rate_limit_delay
        self._last_request_time: float | None = None
        self._exec = FacadeExecutor(
            auth=auth,
            transport=transport,
            proxy_pool=proxy_pool,
            retry_policy=retry_policy,
            retry_strategy=retry_strategy,
            max_retry_attempts=max_retry_attempts,
            logger=logger,
            provider_name="lzt",
            pre_execute=self._throttle,
        )

    # ---------------------------------------------------------------------------
    # Throttle (LZT-specific: 0.2s between requests)
    # ---------------------------------------------------------------------------

    def _throttle(self) -> None:
        """Enforce per-instance minimum delay between requests.

        LZT Market expects at least ~200ms between requests per client.
        """
        if self._rate_limit_delay <= 0:
            return
        now = time.monotonic()
        if self._last_request_time is not None:
            elapsed = now - self._last_request_time
            if elapsed < self._rate_limit_delay:
                time.sleep(self._rate_limit_delay - elapsed)
        self._last_request_time = time.monotonic()

    # ---------------------------------------------------------------------------
    # Category Listings
    # ---------------------------------------------------------------------------

    def get_listings(
        self,
        category: str,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[LztListingPage]:
        """Fetch category listings (e.g. steam, roblox, supercell).

        The app layer constructs category-specific query params
        (pmin, pmax, robux_min, game, page, order_by, etc.) and
        passes them via ``params``.
        """
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_listings(
                category,
                params=params,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Item Details
    # ---------------------------------------------------------------------------

    def get_item(
        self,
        item_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Get single item details by ID."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_item(
                item_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # User Orders
    # ---------------------------------------------------------------------------

    def get_user_orders(
        self,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[LztOrderPage]:
        """Fetch user orders / purchased accounts.

        Supports pagination and filter params via ``params``
        (page, sort, order, login, etc.).
        """
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_user_orders(
                params=params,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # User Items (own listings)
    # ---------------------------------------------------------------------------

    def get_user_items(
        self,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[LztOrderPage]:
        """Fetch user's own items/listings (e.g. closed/sold accounts)."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_user_items(
                params=params,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Mail Access (email:password validation + inbox)
    # ---------------------------------------------------------------------------

    def get_email_letters(
        self,
        email_password: str,
        *,
        limit: int = 50,
        proxy_group: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Validate an ``email:password`` pair and fetch recent inbox letters.

        Wraps ``LztClient.get_email_letters`` with the standard retry,
        proxy rotation, and rate-limit plumbing.  Returns the raw LZT
        response body (``letters``, ``system_info``, ...) on success.

        A 403 result indicates invalid credentials (wrong password or the
        mailbox is locked).  A body-level ``retry_request`` is surfaced as
        a retryable ``SERVER_ERROR`` so the policy will re-issue the call.
        """
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_email_letters(
                email_password=email_password,
                limit=limit,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Check Account (pre-purchase availability check)
    # ---------------------------------------------------------------------------

    def check_account(
        self,
        item_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[LztCheckAccountResult]:
        """Pre-purchase availability and pricing check.

        Idempotent/read-like — verifies the item is still available and
        returns current pricing.  Safe to retry on transient failures.
        """
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.check_account(
                item_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Confirm Buy (purchase execution)
    # ---------------------------------------------------------------------------

    def confirm_buy(
        self,
        item_id: str,
        price: float,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[LztPurchaseResult]:
        """Execute a purchase for the given item.

        Non-idempotent — deducts funds and transfers account ownership.
        Uses ``execute_once`` to prevent duplicate purchases on transient
        failures.  The ``price`` must match the current LZT price
        (server-side race-condition guard).
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.confirm_buy(
                item_id,
                price,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )
