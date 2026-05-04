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
    GameBoostAccountOfferActionResponse,
    GameBoostAccountOfferTemplate,
    GameBoostAddCredentialsResponse,
    GameBoostBulkDeleteCredentialsResponse,
    GameBoostCredentialEntry,
    GameBoostCurrencyOffer,
    GameBoostCurrencyOfferActionResponse,
    GameBoostCurrencyOfferTemplate,
    GameBoostCurrencyOrder,
    GameBoostCurrencyOrderActionResponse,
    GameBoostGiftCard,
    GameBoostGiftCardAddStockResponse,
    GameBoostGiftCardBrand,
    GameBoostGiftCardOffer,
    GameBoostGiftCardOrder,
    GameBoostGiftCardRegion,
    GameBoostItemOffer,
    GameBoostItemOfferActionResponse,
    GameBoostItemOfferTemplate,
    GameBoostItemOrder,
    GameBoostItemOrderActionResponse,
    GameBoostMessage,
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

    def update_account_offer(
        self,
        account_id: str,
        payload: dict[str, Any],
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

    def list_account_offer_action(
        self, account_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostAccountOfferActionResponse]: ...

    def unlist_account_offer_action(
        self, account_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostAccountOfferActionResponse]: ...

    def duplicate_account_offer(
        self, account_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostAccountOfferActionResponse]: ...

    def get_account_offer_template(
        self, game_slug: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostAccountOfferTemplate]: ...

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

    def list_order_messages(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostMessage]]:
        ...

    def send_order_message(
        self,
        order_id: str,
        message: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostMessage]:
        ...

    def update_order_credentials(
        self,
        order_id: str,
        credentials: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostOrder]:
        ...

    # Item Offers
    def list_item_offers(
        self, *, auth_headers: dict[str, str],
        params: dict[str, Any] | None = None, proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostItemOffer]]: ...

    def get_item_offer(
        self, offer_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOffer]: ...

    def create_item_offer(
        self, payload: dict[str, Any], *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOffer]: ...

    def update_item_offer(
        self, offer_id: str, payload: dict[str, Any], *,
        auth_headers: dict[str, str], proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOffer]: ...

    def list_item_offer_action(
        self, offer_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOfferActionResponse]: ...

    def unlist_item_offer_action(
        self, offer_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOfferActionResponse]: ...

    def archive_item_offer_action(
        self, offer_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOfferActionResponse]: ...

    def get_item_offer_template(
        self, game_slug: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOfferTemplate]: ...

    def list_item_offer_orders(
        self, offer_id: str, *, auth_headers: dict[str, str],
        params: dict[str, Any] | None = None, proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostItemOrder]]: ...

    # Item Orders
    def list_item_orders(
        self, *, auth_headers: dict[str, str],
        params: dict[str, Any] | None = None, proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostItemOrder]]: ...

    def get_item_order(
        self, order_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOrder]: ...

    def complete_item_order(
        self, order_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOrderActionResponse]: ...

    def list_item_order_messages(
        self, order_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostMessage]]: ...

    def send_item_order_message(
        self, order_id: str, message: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostMessage]: ...

    # Gift Card Catalog
    def list_gift_cards(
        self, *, auth_headers: dict[str, str],
        params: dict[str, Any] | None = None, proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostGiftCard]]: ...

    def get_gift_card(
        self, gift_card_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostGiftCard]: ...

    def list_gift_card_brands(
        self, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostGiftCardBrand]]: ...

    def list_gift_card_regions(
        self, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostGiftCardRegion]]: ...

    # Gift Card Offers
    def list_gift_card_offers(
        self, *, auth_headers: dict[str, str],
        params: dict[str, Any] | None = None, proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostGiftCardOffer]]: ...

    def get_gift_card_offer(
        self, offer_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostGiftCardOffer]: ...

    def create_gift_card_offer(
        self, payload: dict[str, Any], *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostGiftCardOffer]: ...

    def update_gift_card_offer(
        self, offer_id: str, payload: dict[str, Any], *,
        auth_headers: dict[str, str], proxy_url: str | None = None,
    ) -> ApiResult[GameBoostGiftCardOffer]: ...

    def delete_gift_card_offer(
        self, offer_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[None]: ...

    def add_gift_card_offer_stock(
        self, offer_id: str, keys: list[str], *,
        auth_headers: dict[str, str], proxy_url: str | None = None,
    ) -> ApiResult[GameBoostGiftCardAddStockResponse]: ...

    def remove_gift_card_offer_stock_item(
        self, offer_id: str, delivery_id: str, *,
        auth_headers: dict[str, str], proxy_url: str | None = None,
    ) -> ApiResult[None]: ...

    # Gift Card Orders
    def list_gift_card_orders(
        self, *, auth_headers: dict[str, str],
        params: dict[str, Any] | None = None, proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostGiftCardOrder]]: ...

    def get_gift_card_order(
        self, order_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostGiftCardOrder]: ...

    # Currency Offers
    def list_currency_offers(
        self, *, auth_headers: dict[str, str],
        params: dict[str, Any] | None = None, proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostCurrencyOffer]]: ...

    def get_currency_offer(
        self, offer_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOffer]: ...

    def create_currency_offer(
        self, payload: dict[str, Any], *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOffer]: ...

    def update_currency_offer(
        self, offer_id: str, payload: dict[str, Any], *,
        auth_headers: dict[str, str], proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOffer]: ...

    def list_currency_offer_action(
        self, offer_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOfferActionResponse]: ...

    def unlist_currency_offer_action(
        self, offer_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOfferActionResponse]: ...

    def archive_currency_offer_action(
        self, offer_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOfferActionResponse]: ...

    def get_currency_offer_template(
        self, game_slug: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOfferTemplate]: ...

    def list_currency_offer_orders(
        self, offer_id: str, *, auth_headers: dict[str, str],
        params: dict[str, Any] | None = None, proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostCurrencyOrder]]: ...

    # Currency Orders
    def list_currency_orders(
        self, *, auth_headers: dict[str, str],
        params: dict[str, Any] | None = None, proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostCurrencyOrder]]: ...

    def get_currency_order(
        self, order_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOrder]: ...

    def complete_currency_order(
        self, order_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOrderActionResponse]: ...

    def list_currency_order_messages(
        self, order_id: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostMessage]]: ...

    def send_currency_order_message(
        self, order_id: str, message: str, *, auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostMessage]: ...


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

    def create_offer_with_credentials(
        self,
        payload: dict[str, Any],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Create an account offer with multi-credential support.

        POST /account-offers/create — newer endpoint that accepts a
        ``credentials`` list instead of individual login/password fields.
        Not retried — POST is non-idempotent.
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.create_account_offer_with_credentials(
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

    def update_offer(
        self,
        account_id: str,
        payload: dict[str, Any],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostOffer]:
        """Update an existing account offer.

        PATCH is idempotent — safe to retry.
        """
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.update_account_offer(
                account_id,
                payload,
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

    def list_account_offer(
        self,
        account_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostAccountOfferActionResponse]:
        """Publish (list) an account offer.

        State transition — not retried (POST, non-idempotent).
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.list_account_offer_action(
                account_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def unlist_account_offer(
        self,
        account_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostAccountOfferActionResponse]:
        """Unlist (draft) an account offer.

        State transition — not retried (POST, non-idempotent).
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.unlist_account_offer_action(
                account_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def duplicate_offer(
        self,
        account_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostAccountOfferActionResponse]:
        """Duplicate an account offer.

        Creates a new offer in draft status.
        Not retried — POST is non-idempotent.
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.duplicate_account_offer(
                account_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def get_account_offer_template(
        self,
        game_slug: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostAccountOfferTemplate]:
        """Get account offer creation template for a game."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_account_offer_template(
                game_slug,
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

    def list_order_messages(
        self,
        order_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostMessage]]:
        """List messages for an account order."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_order_messages(
                order_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def send_order_message(
        self,
        order_id: str,
        message: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostMessage]:
        """Send a message to an account order.

        Not retried — POST is non-idempotent.
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.send_order_message(
                order_id,
                message,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def update_order_credentials(
        self,
        order_id: str,
        credentials: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostOrder]:
        """Update credentials for an account order.

        PATCH is idempotent — safe to retry.
        """
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.update_order_credentials(
                order_id,
                credentials,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Item Offers
    # ---------------------------------------------------------------------------

    def list_item_offers(
        self,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostItemOffer]]:
        """List item offers with optional filters and pagination."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_item_offers(
                auth_headers=self._exec.get_auth_headers(),
                params=params,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def get_item_offer(
        self,
        offer_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostItemOffer]:
        """Get a single item offer by ID."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_item_offer(
                offer_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def create_item_offer(
        self,
        payload: dict[str, Any],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostItemOffer]:
        """Create a new item offer.

        Not retried — POST is non-idempotent.
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.create_item_offer(
                payload,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def update_item_offer(
        self,
        offer_id: str,
        payload: dict[str, Any],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostItemOffer]:
        """Update an existing item offer.

        PATCH is idempotent — safe to retry.
        """
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.update_item_offer(
                offer_id,
                payload,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def list_item_offer(
        self,
        offer_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostItemOfferActionResponse]:
        """Publish (list) an item offer.

        State transition — not retried (POST, non-idempotent).
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.list_item_offer_action(
                offer_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def unlist_item_offer(
        self,
        offer_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostItemOfferActionResponse]:
        """Unlist (draft) an item offer.

        State transition — not retried (POST, non-idempotent).
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.unlist_item_offer_action(
                offer_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def archive_item_offer(
        self,
        offer_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostItemOfferActionResponse]:
        """Archive an item offer.

        State transition — not retried (POST, non-idempotent).
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.archive_item_offer_action(
                offer_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def get_item_offer_template(
        self,
        game_slug: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostItemOfferTemplate]:
        """Get item offer creation template for a game."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_item_offer_template(
                game_slug,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def list_item_offer_orders(
        self,
        offer_id: str,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostItemOrder]]:
        """List orders for a specific item offer."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_item_offer_orders(
                offer_id,
                auth_headers=self._exec.get_auth_headers(),
                params=params,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Item Orders
    # ---------------------------------------------------------------------------

    def list_item_orders(
        self,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostItemOrder]]:
        """List item orders with optional filters and pagination."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_item_orders(
                auth_headers=self._exec.get_auth_headers(),
                params=params,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def get_item_order(
        self,
        order_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostItemOrder]:
        """Get a single item order by ID."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_item_order(
                order_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def complete_item_order(
        self,
        order_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostItemOrderActionResponse]:
        """Complete an item order.

        State transition — not retried (POST, non-idempotent).
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.complete_item_order(
                order_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def list_item_order_messages(
        self,
        order_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostMessage]]:
        """List messages for an item order."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_item_order_messages(
                order_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def send_item_order_message(
        self,
        order_id: str,
        message: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostMessage]:
        """Send a message to an item order.

        Not retried — POST is non-idempotent.
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.send_item_order_message(
                order_id,
                message,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Gift Card Catalog
    # ---------------------------------------------------------------------------

    def list_gift_cards(
        self,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostGiftCard]]:
        """List gift card catalog entries with pagination."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_gift_cards(
                auth_headers=self._exec.get_auth_headers(),
                params=params,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def get_gift_card(
        self,
        gift_card_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostGiftCard]:
        """Get a single gift card catalog entry by ID."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_gift_card(
                gift_card_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def list_gift_card_brands(
        self,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostGiftCardBrand]]:
        """List all gift card brands."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_gift_card_brands(
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def list_gift_card_regions(
        self,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostGiftCardRegion]]:
        """List all gift card regions."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_gift_card_regions(
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Gift Card Offers
    # ---------------------------------------------------------------------------

    def list_gift_card_offers(
        self,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostGiftCardOffer]]:
        """List gift card offers with optional filters and pagination."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_gift_card_offers(
                auth_headers=self._exec.get_auth_headers(),
                params=params,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def get_gift_card_offer(
        self,
        offer_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostGiftCardOffer]:
        """Get a single gift card offer by ID."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_gift_card_offer(
                offer_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def create_gift_card_offer(
        self,
        payload: dict[str, Any],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostGiftCardOffer]:
        """Create a new gift card offer.

        Not retried — POST is non-idempotent.
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.create_gift_card_offer(
                payload,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def update_gift_card_offer(
        self,
        offer_id: str,
        payload: dict[str, Any],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostGiftCardOffer]:
        """Update a gift card offer (price).

        PATCH is idempotent — safe to retry.
        """
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.update_gift_card_offer(
                offer_id,
                payload,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def delete_gift_card_offer(
        self,
        offer_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[None]:
        """Delete a gift card offer."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.delete_gift_card_offer(
                offer_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def add_gift_card_offer_stock(
        self,
        offer_id: str,
        keys: list[str],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostGiftCardAddStockResponse]:
        """Add stock (keys) to a gift card offer.

        Not retried — POST is non-idempotent.
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.add_gift_card_offer_stock(
                offer_id,
                keys,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def remove_gift_card_offer_stock_item(
        self,
        offer_id: str,
        delivery_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[None]:
        """Remove a single stock item from a gift card offer."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.remove_gift_card_offer_stock_item(
                offer_id,
                delivery_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Gift Card Orders
    # ---------------------------------------------------------------------------

    def list_gift_card_orders(
        self,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostGiftCardOrder]]:
        """List gift card orders with optional filters and pagination."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_gift_card_orders(
                auth_headers=self._exec.get_auth_headers(),
                params=params,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def get_gift_card_order(
        self,
        order_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostGiftCardOrder]:
        """Get a single gift card order by ID."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_gift_card_order(
                order_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Currency Offers
    # ---------------------------------------------------------------------------

    def list_currency_offers(
        self,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostCurrencyOffer]]:
        """List currency offers with optional filters and pagination."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_currency_offers(
                auth_headers=self._exec.get_auth_headers(),
                params=params,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def get_currency_offer(
        self,
        offer_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOffer]:
        """Get a single currency offer by ID."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_currency_offer(
                offer_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def create_currency_offer(
        self,
        payload: dict[str, Any],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOffer]:
        """Create a new currency offer.

        Not retried — POST is non-idempotent.
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.create_currency_offer(
                payload,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def update_currency_offer(
        self,
        offer_id: str,
        payload: dict[str, Any],
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOffer]:
        """Update an existing currency offer.

        PATCH is idempotent — safe to retry.
        """
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.update_currency_offer(
                offer_id,
                payload,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def list_currency_offer(
        self,
        offer_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOfferActionResponse]:
        """Publish (list) a currency offer.

        State transition — not retried (POST, non-idempotent).
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.list_currency_offer_action(
                offer_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def unlist_currency_offer(
        self,
        offer_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOfferActionResponse]:
        """Unlist (draft) a currency offer.

        State transition — not retried (POST, non-idempotent).
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.unlist_currency_offer_action(
                offer_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def archive_currency_offer(
        self,
        offer_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOfferActionResponse]:
        """Archive a currency offer.

        State transition — not retried (POST, non-idempotent).
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.archive_currency_offer_action(
                offer_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def get_currency_offer_template(
        self,
        game_slug: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOfferTemplate]:
        """Get currency offer creation template for a game."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_currency_offer_template(
                game_slug,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def list_currency_offer_orders(
        self,
        offer_id: str,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostCurrencyOrder]]:
        """List orders for a specific currency offer."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_currency_offer_orders(
                offer_id,
                auth_headers=self._exec.get_auth_headers(),
                params=params,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    # ---------------------------------------------------------------------------
    # Currency Orders
    # ---------------------------------------------------------------------------

    def list_currency_orders(
        self,
        *,
        params: dict[str, Any] | None = None,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostCurrencyOrder]]:
        """List currency orders with optional filters and pagination."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_currency_orders(
                auth_headers=self._exec.get_auth_headers(),
                params=params,
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def get_currency_order(
        self,
        order_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOrder]:
        """Get a single currency order by ID."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.get_currency_order(
                order_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def complete_currency_order(
        self,
        order_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOrderActionResponse]:
        """Complete a currency order.

        State transition — not retried (POST, non-idempotent).
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.complete_currency_order(
                order_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def list_currency_order_messages(
        self,
        order_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[list[GameBoostMessage]]:
        """List messages for a currency order."""
        return self._exec.execute_with_retry(
            lambda proxy_url: self._client.list_currency_order_messages(
                order_id,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )

    def send_currency_order_message(
        self,
        order_id: str,
        message: str,
        *,
        proxy_group: str | None = None,
    ) -> ApiResult[GameBoostMessage]:
        """Send a message to a currency order.

        Not retried — POST is non-idempotent.
        """
        return self._exec.execute_once(
            lambda proxy_url: self._client.send_currency_order_message(
                order_id,
                message,
                auth_headers=self._exec.get_auth_headers(),
                proxy_url=proxy_url,
            ),
            proxy_group=proxy_group,
        )
