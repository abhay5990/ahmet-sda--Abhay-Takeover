"""
G2G high-level facade.

Provides a clean consumer-facing API that coordinates:
- Authentication
- Optional proxy selection
- Retry policy execution with strategy-driven actions
- Per-instance request throttling (0.5s between requests)

Lifecycle:
    Facade instances are intended to be long-lived (one per worker/process
    per store account). The transport, auth provider, and proxy pool are
    injected at construction and reused across all calls.

    The facade does NOT own the transport session. Callers who create the
    transport are responsible for calling ``transport.close()`` at shutdown.

Critical design decisions:
    create_offer() does NOT go through execute_with_retry().
    G2G's create offer is a non-idempotent POST — retrying could create
    duplicate offers. create_offer() makes a single attempt with proxy
    acquisition only.

    A per-instance rate-limit throttle (0.5s default) is applied before
    each operation to respect G2G's rate expectations.
"""

from __future__ import annotations

import time
from typing import Any, Protocol, TypeVar

from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.auth.base import BaseAuthProvider
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.infrastructure.retry.policy import RetryPolicy
from apis_sdk.infrastructure.retry.strategy import RetryStrategy
from apis_sdk.clients.marketplaces._facade_support import FacadeExecutor

T = TypeVar("T")


class G2GApiClient(Protocol):
    """Protocol for the low-level G2G client."""

    def create_offer(
        self,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        ...

    def update_offer(
        self,
        offer_id: str,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        ...

    def delete_offer(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[None]:
        ...

    def get_offers(
        self,
        *,
        auth_headers: dict[str, str],
        page: int = 1,
        page_size: int = 20,
        status: str = "active",
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        ...


class G2GFacade:
    """
    High-level G2G marketplace interface.

    Coordinates authentication, proxy rotation, retry logic,
    and per-instance throttling around the low-level G2GClient.
    """

    def __init__(
        self,
        client: G2GApiClient,
        auth: BaseAuthProvider,
        *,
        transport: BaseHttpTransport | None = None,
        proxy_pool: ProxyPool | None = None,
        retry_policy: RetryPolicy | None = None,
        retry_strategy: RetryStrategy | None = None,
        max_retry_attempts: int = 3,
        rate_limit_delay: float = 0.5,
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
            provider_name="g2g",
            pre_execute=self._throttle,
        )

    # ---------------------------------------------------------------------------
    # Throttle (G2G-specific)
    # ---------------------------------------------------------------------------

    def _throttle(self) -> None:
        """Enforce per-instance minimum delay between requests.

        G2G expects at least 0.5s between requests per client instance.
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
    # Offers
    # ---------------------------------------------------------------------------

    def create_offer(
        self,
        payload: dict[str, Any],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Create a new offer on G2G.

        This operation is NOT retried automatically. POST offer creation
        is non-idempotent: retrying could create duplicate offers.
        The caller is responsible for retry decisions.
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.create_offer(
                payload,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def update_offer(
        self,
        offer_id: str,
        payload: dict[str, Any],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Update an existing offer."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.update_offer(
                offer_id,
                payload,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def delete_offer(
        self,
        offer_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[None]:
        """Delete an offer."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.delete_offer(
                offer_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def get_offers(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str = "active",
        proxy_group: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """List seller's offers with pagination."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_offers(
                auth_headers=self._exec.get_auth_headers(),
                page=page,
                page_size=page_size,
                status=status,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )
