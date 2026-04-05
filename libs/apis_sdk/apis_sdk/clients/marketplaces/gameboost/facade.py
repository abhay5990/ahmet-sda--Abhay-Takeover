"""
GameBoost high-level facade.

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
    GameBoost's legacy client explicitly excludes POST from urllib3's
    retry allowed_methods list, confirming that POST is not considered
    safe to auto-retry. A duplicate offer creation would be harmful.
    create_offer() makes a single attempt with proxy acquisition only.
"""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.auth.base import BaseAuthProvider
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import SdkLogger
from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.infrastructure.retry.policy import RetryPolicy
from apis_sdk.infrastructure.retry.strategy import RetryStrategy
from apis_sdk.clients.marketplaces._facade_support import FacadeExecutor
from apis_sdk.clients.marketplaces.gameboost.models import (
    GameBoostAddCredentialsResponse,
    GameBoostBulkDeleteCredentialsResponse,
    GameBoostCredentialEntry,
    GameBoostOffer,
    GameBoostOrder,
)

T = TypeVar("T")


class GameBoostApiClient(Protocol):
    """Protocol for the low-level GameBoost client."""

    def create_account_offer(
        self,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        ...

    def list_account_offers(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostOffer]]:
        ...

    def get_account_offer(
        self,
        account_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostOffer]:
        ...

    def delete_account_offer(
        self,
        account_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[None]:
        ...

    def list_offer_credentials(
        self,
        account_id: str,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostCredentialEntry]]:
        ...

    def add_offer_credentials(
        self,
        account_id: str,
        credentials: list[str],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostAddCredentialsResponse]:
        ...

    def delete_offer_credential(
        self,
        account_id: str,
        credential_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[None]:
        ...

    def bulk_delete_offer_credentials(
        self,
        account_id: str,
        credential_ids: list[int],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostBulkDeleteCredentialsResponse]:
        ...

    def update_offer_credential(
        self,
        account_id: str,
        credential_id: str,
        credentials: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCredentialEntry]:
        ...

    def list_account_orders(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostOrder]]:
        ...

    def get_account_order(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostOrder]:
        ...


class GameBoostFacade:
    """
    High-level GameBoost marketplace interface.

    Coordinates authentication, proxy rotation, and retry logic around
    the low-level GameBoostClient.
    """

    def __init__(
        self,
        client: GameBoostApiClient,
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
            provider_name="gameboost",
        )

    # ---------------------------------------------------------------------------
    # Account Offers
    # ---------------------------------------------------------------------------

    def create_offer(
        self,
        payload: dict[str, Any],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Create a new account offer on GameBoost.

        This operation is NOT retried automatically. POST offer creation
        is non-idempotent: retrying could create duplicate offers.
        The caller is responsible for retry decisions.
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.create_account_offer(
                payload,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def list_offers(
        self,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostOffer]]:
        """List account offers with optional filters and pagination."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_account_offers(
                auth_headers=self._exec.get_auth_headers(),
                params=params,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def get_offer(
        self,
        account_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostOffer]:
        """Get a single account offer by ID."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_account_offer(
                account_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def delete_offer(
        self,
        account_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[None]:
        """Delete an account offer."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.delete_account_offer(
                account_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Offer Credentials
    # ---------------------------------------------------------------------------

    def list_offer_credentials(
        self,
        account_id: str,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostCredentialEntry]]:
        """List credentials for an account offer (paginated)."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_offer_credentials(
                account_id,
                auth_headers=self._exec.get_auth_headers(),
                params=params,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def add_offer_credentials(
        self,
        account_id: str,
        credentials: list[str],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostAddCredentialsResponse]:
        """Add credentials to an account offer (non-legacy only).

        Duplicates within the same offer are automatically skipped.
        Not retried — POST is non-idempotent.
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.add_offer_credentials(
                account_id,
                credentials,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def delete_offer_credential(
        self,
        account_id: str,
        credential_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[None]:
        """Delete a single credential from an account offer (non-legacy only).

        Sold credentials cannot be deleted.
        """
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.delete_offer_credential(
                account_id,
                credential_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def bulk_delete_offer_credentials(
        self,
        account_id: str,
        credential_ids: list[int],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostBulkDeleteCredentialsResponse]:
        """Bulk delete credentials from an account offer (non-legacy only).

        Sold credentials are skipped automatically.
        Not retried — POST is non-idempotent.
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.bulk_delete_offer_credentials(
                account_id,
                credential_ids,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def update_offer_credential(
        self,
        account_id: str,
        credential_id: str,
        credentials: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostCredentialEntry]:
        """Update a single credential on an account offer (non-legacy only).

        Sold credentials cannot be updated.
        """
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.update_offer_credential(
                account_id,
                credential_id,
                credentials,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Account Orders
    # ---------------------------------------------------------------------------

    def list_orders(
        self,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostOrder]]:
        """List account orders with optional filters and pagination."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_account_orders(
                auth_headers=self._exec.get_auth_headers(),
                params=params,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def get_order(
        self,
        order_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostOrder]:
        """Get a single account order by ID."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_account_order(
                order_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )
