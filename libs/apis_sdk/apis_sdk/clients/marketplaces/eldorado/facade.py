"""
Eldorado high-level facade.

Provides a clean consumer-facing API that coordinates:
- Authentication
- Optional proxy selection
- Retry policy execution with strategy-driven actions

Lifecycle:
    Facade instances are intended to be long-lived (one per worker/process
    per store account). The transport, auth provider, and proxy pool are
    injected at construction and reused across all calls.

    The facade does NOT own the transport session. Callers who create the
    transport are responsible for calling ``transport.close()`` at shutdown.
    A facade-level ``close()`` is intentionally deferred until ownership
    semantics are clarified for shared-transport scenarios.

Critical design decision:
    create_offer() does NOT go through execute_with_retry().
    POST offer creation is non-idempotent: retrying could create duplicate
    offers.  create_offer() makes a single attempt with proxy acquisition
    only — consistent with GameBoost and G2G.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.auth.base import BaseAuthProvider
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.infrastructure.retry.policy import RetryPolicy
from apis_sdk.infrastructure.retry.strategy import RetryStrategy
from apis_sdk.clients.marketplaces._facade_support import FacadeExecutor
from apis_sdk.clients.marketplaces.eldorado.exceptions import (
    EldoradoProviderNotReadyError,
)
from apis_sdk.clients.marketplaces.eldorado.models import (
    EldoradoOffer,
    EldoradoOfferCredentialsResponse,
    EldoradoOfferSearchPage,
    EldoradoOfferStateCount,
    EldoradoOrder,
    EldoradoOrderAccountDetails,
    EldoradoSellerOrdersPage,
)

T = TypeVar("T")


class EldoradoApiClient(Protocol):
    def create_offer(
        self,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoOffer]:
        ...

    def update_offer(
        self,
        offer_id: str,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoOffer]:
        ...

    def delete_offer(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[None]:
        ...

    def search_my_offers(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoOfferSearchPage]:
        ...

    def get_seller_orders(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoSellerOrdersPage]:
        ...

    def get_order_by_id(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoOrder]:
        ...

    def upload_image(
        self,
        file_path: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[list[str]]:
        ...

    def get_offer_state_counts(
        self,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoOfferStateCount]:
        ...

    def get_order_account_details(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoOrderAccountDetails]:
        ...

    def get_offer_account_details(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoOfferCredentialsResponse]:
        ...


def _eldorado_exception_hook(exc: Exception) -> ApiResult[Any] | None:
    """Handle EldoradoProviderNotReadyError before generic conversion."""
    if isinstance(exc, EldoradoProviderNotReadyError):
        return ApiResult.from_error(
            ErrorCategory.VALIDATION,
            str(exc),
            provider=exc.provider,
            is_retryable=False,
            details=exc.details,
        )
    return None


class EldoradoFacade:
    """
    High-level Eldorado marketplace interface.

    Coordinates authentication, proxy rotation, and retry logic around
    the low-level EldoradoClient.
    """

    def __init__(
        self,
        client: EldoradoApiClient,
        auth: BaseAuthProvider,
        *,
        transport: BaseHttpTransport | None = None,
        proxy_pool: ProxyPool | None = None,
        retry_policy: RetryPolicy | None = None,
        retry_strategy: RetryStrategy | None = None,
        max_retry_attempts: int = 3,
        logger: SdkLogger | None = None,
    ) -> None:
        self._client = client
        self._exec = FacadeExecutor(
            auth=auth,
            transport=transport,
            proxy_pool=proxy_pool,
            retry_policy=retry_policy,
            retry_strategy=retry_strategy,
            max_retry_attempts=max_retry_attempts,
            logger=logger,
            provider_name="eldorado",
            exception_hook=_eldorado_exception_hook,
        )

    # ---------------------------------------------------------------------------
    # Offers
    # ---------------------------------------------------------------------------

    def create_offer(
        self,
        payload: dict[str, Any],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[EldoradoOffer]:
        """Create a new offer on Eldorado.

        This operation is NOT retried automatically.  POST offer creation
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
    ) -> ApiResult[EldoradoOffer]:
        """Update an existing offer on Eldorado."""
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
        """Delete an offer from Eldorado."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.delete_offer(
                offer_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def search_my_offers(
        self,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[EldoradoOfferSearchPage]:
        """Search the seller's own offers (paginated)."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.search_my_offers(
                auth_headers=self._exec.get_auth_headers(),
                params=params,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Orders
    # ---------------------------------------------------------------------------

    def get_seller_orders(
        self,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[EldoradoSellerOrdersPage]:
        """Fetch a paginated page of seller orders from Eldorado."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_seller_orders(
                auth_headers=self._exec.get_auth_headers(),
                params=params,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def get_order_by_id(
        self,
        order_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[EldoradoOrder]:
        """Fetch a single order by its ID."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_order_by_id(
                order_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Images
    # ---------------------------------------------------------------------------

    def upload_image(
        self,
        file_path: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[list[str]]:
        """Upload an image to Eldorado."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.upload_image(
                file_path,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Offer state
    # ---------------------------------------------------------------------------

    def get_offer_state_counts(
        self,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[EldoradoOfferStateCount]:
        """Fetch offer state counts (active, inactive, pending, suspended)."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_offer_state_counts(
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Order details
    # ---------------------------------------------------------------------------

    def get_order_account_details(
        self,
        order_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[EldoradoOrderAccountDetails]:
        """Fetch account/credential details for a completed order."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_order_account_details(
                order_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def get_offer_account_details(
        self,
        offer_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[EldoradoOfferCredentialsResponse]:
        """Fetch credential details for an offer (by offer ID)."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_offer_account_details(
                offer_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )
