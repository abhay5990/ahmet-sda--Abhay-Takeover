"""
PlayerAuctions high-level facade.

Provides a clean consumer-facing API that coordinates:
- Authentication
- Optional proxy selection
- Retry policy execution with strategy-driven actions
- Per-instance request throttling (1.0s between requests)

Lifecycle:
    Facade instances are intended to be long-lived (one per worker/process
    per store account). The transport, auth provider, and proxy pool are
    injected at construction and reused across all calls.

    The facade does NOT own the transport session. Callers who create the
    transport are responsible for calling ``transport.close()`` at shutdown.
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
from apis_sdk.clients.marketplaces.playerauctions.models import (
    PlayerAuctionsBulkUploadResponse,
    PlayerAuctionsCancelRequest,
    PlayerAuctionsCancelResponse,
    PlayerAuctionsCreateOfferResponse,
    PlayerAuctionsOffer,
    PlayerAuctionsOrder,
    PlayerAuctionsOrderDetail,
)


class PlayerAuctionsApiClient(Protocol):
    """Protocol for the low-level PlayerAuctions client."""

    def list_offers(
        self,
        *,
        auth_headers: dict[str, str],
        page: int = 1,
        page_size: int = 50,
        listing_status: str = "",
        proxy_url: str | None = None,
    ) -> ApiResult[list[PlayerAuctionsOffer]]:
        ...

    def get_offer_details(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        ...

    def list_seller_orders(
        self,
        *,
        auth_headers: dict[str, str],
        page: int = 1,
        page_size: int = 50,
        order_status: str = "All",
        product_type: str = "Accounts",
        proxy_url: str | None = None,
    ) -> ApiResult[list[PlayerAuctionsOrder]]:
        ...

    def get_order_details(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[PlayerAuctionsOrderDetail]:
        ...

    def create_offer(
        self,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[PlayerAuctionsCreateOfferResponse]:
        ...

    def cancel_offers(
        self,
        request: PlayerAuctionsCancelRequest,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[PlayerAuctionsCancelResponse]:
        ...

    def game_account_servers(
        self,
        game_id: int,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[list[dict[str, Any]]]:
        ...

    def bulk_upload(
        self,
        file_path: str,
        *,
        product_type: str = "Accounts",
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[PlayerAuctionsBulkUploadResponse]:
        ...


class PlayerAuctionsFacade:
    """
    High-level PlayerAuctions marketplace interface.

    Coordinates authentication, proxy rotation, retry logic,
    and per-instance throttling around the low-level client.

    Read/idempotent operations use execute_with_retry().
    Write operations use execute_once() to prevent duplicate side effects.
    """

    def __init__(
        self,
        client: PlayerAuctionsApiClient,
        auth: BaseAuthProvider,
        *,
        transport: BaseHttpTransport | None = None,
        proxy_pool: ProxyPool | None = None,
        retry_policy: RetryPolicy | None = None,
        retry_strategy: RetryStrategy | None = None,
        max_retry_attempts: int = 3,
        rate_limit_delay: float = 1.0,
        logger: SdkLogger | None = None,
    ) -> None:
        self._client = client
        self._rate_limit_delay = rate_limit_delay
        self._last_request_time: float | None = None
        self._auth = auth
        self._exec = FacadeExecutor(
            auth=auth,
            transport=transport,
            proxy_pool=proxy_pool,
            retry_policy=retry_policy,
            retry_strategy=retry_strategy,
            max_retry_attempts=max_retry_attempts,
            logger=logger,
            provider_name="playerauctions",
            pre_execute=self._throttle,
        )

    def reset_auth_failure(self) -> None:
        """Reset auth failure flag so the next 401 can trigger a fresh refresh."""
        if hasattr(self._auth, 'reset_failure'):
            self._auth.reset_failure()

    # ---------------------------------------------------------------------------
    # Throttle (PlayerAuctions-specific)
    # ---------------------------------------------------------------------------

    def _throttle(self) -> None:
        """Enforce per-instance minimum delay between requests.

        PlayerAuctions expects at least 1.0s between requests per client
        instance. This matches the legacy instance-level rate limiting.
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
    # Offers — read operations
    # ---------------------------------------------------------------------------

    def list_offers(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        listing_status: str = "",
        proxy_group: str | None = None,
    ) -> ApiResult[list[PlayerAuctionsOffer]]:
        """List seller offers with pagination."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_offers(
                auth_headers=self._exec.get_auth_headers(),
                page=page,
                page_size=page_size,
                listing_status=listing_status,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def get_offer_details(
        self,
        offer_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Fetch a specific offer by ID."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_offer_details(
                offer_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Orders — list operations
    # ---------------------------------------------------------------------------

    def list_seller_orders(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        order_status: str = "All",
        product_type: str = "Accounts",
        proxy_group: str | None = None,
    ) -> ApiResult[list[PlayerAuctionsOrder]]:
        """List seller orders with filters and pagination."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_seller_orders(
                auth_headers=self._exec.get_auth_headers(),
                page=page,
                page_size=page_size,
                order_status=order_status,
                product_type=product_type,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Orders — detail operations
    # ---------------------------------------------------------------------------

    def get_order_details(
        self,
        order_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[PlayerAuctionsOrderDetail]:
        """Fetch order details by order ID (idempotent read)."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_order_details(
                order_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Offers — write operations
    # ---------------------------------------------------------------------------

    def create_offer(
        self,
        payload: dict[str, Any],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[PlayerAuctionsCreateOfferResponse]:
        """Create a single offer (non-idempotent, no retry)."""
        return self._exec.execute_once(
            lambda proxy_url: self._client.create_offer(
                payload,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def cancel_offers(
        self,
        request: PlayerAuctionsCancelRequest,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[PlayerAuctionsCancelResponse]:
        """Cancel offers by IDs (non-idempotent, no retry)."""
        return self._exec.execute_once(
            lambda proxy_url: self._client.cancel_offers(
                request,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Offers — bulk operations
    # ---------------------------------------------------------------------------

    def bulk_upload(
        self,
        file_path: str,
        *,
        product_type: str = "Accounts",
        proxy_group: str | None = None,
    ) -> ApiResult[PlayerAuctionsBulkUploadResponse]:
        """Upload an Excel file for bulk offer creation (non-idempotent, no retry)."""
        return self._exec.execute_once(
            lambda proxy_url: self._client.bulk_upload(
                file_path,
                product_type=product_type,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Games — reference data
    # ---------------------------------------------------------------------------

    def game_account_servers(
        self,
        game_id: int,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[list[dict[str, Any]]]:
        """Fetch server options for a game (idempotent read)."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.game_account_servers(
                game_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )
