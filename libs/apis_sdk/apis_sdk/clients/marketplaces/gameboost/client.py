"""
Low-level GameBoost API client.

Handles raw HTTP communication with the GameBoost v2 API.
Returns parsed response models with extracted metadata.
The facade layer handles auth header injection, proxy selection,
and retry orchestration.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.clients.marketplaces.gameboost.config import GameBoostConfig
from apis_sdk.clients.marketplaces.gameboost.endpoints import GameBoostEndpoints
from apis_sdk.clients.marketplaces.gameboost.mapper import GameBoostMapper
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


class GameBoostClient:
    """
    Low-level GameBoost API client.

    Handles:
    - Request execution via injected transport
    - Response parsing into GameBoost-specific models
    - Error categorization (including 407 as retryable network error)
    - Metadata extraction (request-id, rate-limit headers, pagination)

    Does NOT handle:
    - Authentication (injected via auth_headers parameter)
    - Retry logic (handled by facade/retry policy)
    - Proxy selection (handled by proxy pool)
    """

    PROVIDER = "gameboost"

    def __init__(
        self,
        config: GameBoostConfig,
        transport: BaseHttpTransport,
        *,
        logger: SdkLogger | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._logger = logger or NullLogger()

    def _build_url(self, path: str) -> str:
        return f"{self._config.base_url}{path}"

    # ---------------------------------------------------------------------------
    # Account Offers
    # ---------------------------------------------------------------------------

    def create_account_offer(
        self,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """
        Create a new account offer on GameBoost.

        Accepts a raw payload dict — game-specific payload building
        is out of scope for the SDK.

        Returns the raw response body on success.
        """
        url = self._build_url(GameBoostEndpoints.ACCOUNT_OFFERS)

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=auth_headers,
                json_body=payload,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse create response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(body, status_code=response.status_code, meta=meta)

    def list_account_offers(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostOffer]]:
        """List account offers with pagination support."""
        url = self._build_url(GameBoostEndpoints.ACCOUNT_OFFERS)

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                params=params,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            offers = [GameBoostOffer.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse offers response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(offers, status_code=response.status_code, meta=meta)

    def get_account_offer(
        self,
        account_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostOffer]:
        """Get a single account offer by ID."""
        return self._request(
            HttpMethod.GET,
            GameBoostEndpoints.account_offer(account_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostOffer,
        )

    def update_account_offer(
        self,
        account_id: str,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostOffer]:
        """Update an existing account offer.

        PATCH /account-offers/{account_id}
        All fields are optional — only provided fields are updated.
        """
        return self._request(
            HttpMethod.PATCH,
            GameBoostEndpoints.account_offer(account_id),
            json_body=payload,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostOffer,
        )

    def delete_account_offer(
        self,
        account_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[None]:
        """Delete an account offer."""
        return self._request(
            HttpMethod.DELETE,
            GameBoostEndpoints.account_offer(account_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=None,
        )

    def list_account_offer_action(
        self,
        account_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostAccountOfferActionResponse]:
        """Publish (list) an account offer.

        POST /account-offers/{account_id}/list  (no body)
        """
        return self._request_action(
            GameBoostEndpoints.account_offer_list_action(account_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostAccountOfferActionResponse,
        )

    def unlist_account_offer_action(
        self,
        account_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostAccountOfferActionResponse]:
        """Unlist (draft) an account offer.

        POST /account-offers/{account_id}/draft  (no body)
        """
        return self._request_action(
            GameBoostEndpoints.account_offer_unlist_action(account_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostAccountOfferActionResponse,
        )

    def duplicate_account_offer(
        self,
        account_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostAccountOfferActionResponse]:
        """Duplicate an account offer.

        POST /account-offers/{account_id}/duplicate  (no body)
        Returns a new offer in draft status.
        """
        return self._request_action(
            GameBoostEndpoints.account_offer_duplicate(account_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostAccountOfferActionResponse,
        )

    def get_account_offer_template(
        self,
        game_slug: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostAccountOfferTemplate]:
        """Get account offer creation template for a game.

        GET /account-offers/templates/{game_slug}
        """
        url = self._build_url(GameBoostEndpoints.account_offer_template(game_slug))

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            data = body.get("template", body) if isinstance(body, dict) else body
            parsed = GameBoostAccountOfferTemplate.model_validate(data)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse account offer template response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(parsed, status_code=response.status_code, meta=meta)

    def list_offer_credentials(
        self,
        account_id: str,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostCredentialEntry]]:
        """List credentials for an account offer (paginated)."""
        url = self._build_url(GameBoostEndpoints.offer_credentials(account_id))

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                params=params,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            entries = [GameBoostCredentialEntry.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse credentials response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(entries, status_code=response.status_code, meta=meta)

    def add_offer_credentials(
        self,
        account_id: str,
        credentials: list[str],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostAddCredentialsResponse]:
        """Add credentials to an account offer (non-legacy only).

        POST /account-offers/{account_id}/credentials
        Body: {"credentials": ["Login: user1\\nPassword: pass1", ...]}
        """
        url = self._build_url(GameBoostEndpoints.offer_credentials(account_id))

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=auth_headers,
                json_body={"credentials": credentials},
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            parsed = GameBoostAddCredentialsResponse.model_validate(body)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse add credentials response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(parsed, status_code=response.status_code, meta=meta)

    def delete_offer_credential(
        self,
        account_id: str,
        credential_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[None]:
        """Delete a single credential from an account offer (non-legacy only).

        DELETE /account-offers/{account_id}/credentials/{credential_id}
        Sold credentials cannot be deleted.
        """
        return self._request(
            HttpMethod.DELETE,
            GameBoostEndpoints.offer_credential(account_id, credential_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=None,
        )

    def bulk_delete_offer_credentials(
        self,
        account_id: str,
        credential_ids: list[int],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostBulkDeleteCredentialsResponse]:
        """Bulk delete credentials from an account offer (non-legacy only).

        POST /account-offers/{account_id}/credentials/bulk-delete
        Body: {"credentials_ids": [1, 2, 3]}
        Sold credentials are skipped.
        """
        url = self._build_url(
            GameBoostEndpoints.offer_credentials_bulk_delete(account_id)
        )

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=auth_headers,
                json_body={"credentials_ids": credential_ids},
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            parsed = GameBoostBulkDeleteCredentialsResponse.model_validate(body)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse bulk delete response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(parsed, status_code=response.status_code, meta=meta)

    def update_offer_credential(
        self,
        account_id: str,
        credential_id: str,
        credentials: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCredentialEntry]:
        """Update a single credential on an account offer (non-legacy only).

        PATCH /account-offers/{account_id}/credentials/{credential_id}
        Body: {"credentials": "Login: updated\\nPassword: newpass"}
        Sold credentials cannot be updated.
        """
        url = self._build_url(
            GameBoostEndpoints.offer_credential(account_id, credential_id)
        )

        try:
            response = self._transport.request(
                HttpMethod.PATCH,
                url,
                headers=auth_headers,
                json_body={"credentials": credentials},
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            data = body.get("data", body) if isinstance(body, dict) else body
            parsed = GameBoostCredentialEntry.model_validate(data)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse update credential response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(parsed, status_code=response.status_code, meta=meta)

    # ---------------------------------------------------------------------------
    # Account Orders
    # ---------------------------------------------------------------------------

    def list_account_orders(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostOrder]]:
        """List account orders with pagination support."""
        url = self._build_url(GameBoostEndpoints.ACCOUNT_ORDERS)

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                params=params,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            orders = [GameBoostOrder.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse orders response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(orders, status_code=response.status_code, meta=meta)

    def get_account_order(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostOrder]:
        """Get a single account order by ID."""
        return self._request(
            HttpMethod.GET,
            GameBoostEndpoints.account_order(order_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostOrder,
        )

    def list_order_messages(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostMessage]]:
        """List messages for an account order.

        GET /account-orders/{order_id}/messages
        """
        url = self._build_url(GameBoostEndpoints.order_messages(order_id))

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            messages = [GameBoostMessage.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse order messages response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(messages, status_code=response.status_code, meta=meta)

    def send_order_message(
        self,
        order_id: str,
        message: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostMessage]:
        """Send a message to an account order.

        POST /account-orders/{order_id}/messages
        Body: {"message": "..."}  (max 10,000 chars)
        """
        url = self._build_url(GameBoostEndpoints.order_messages(order_id))

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=auth_headers,
                json_body={"message": message},
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            data = body.get("data", body) if isinstance(body, dict) else body
            parsed = GameBoostMessage.model_validate(data)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse send message response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(parsed, status_code=response.status_code, meta=meta)

    def update_order_credentials(
        self,
        order_id: str,
        credentials: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostOrder]:
        """Update credentials for an account order.

        PATCH /account-orders/{order_id}/credentials
        Body: {"credentials": "Login: ...\\nPassword: ..."}  (max 10,000 chars)
        """
        return self._request(
            HttpMethod.PATCH,
            GameBoostEndpoints.order_credentials(order_id),
            json_body={"credentials": credentials},
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostOrder,
        )

    # ---------------------------------------------------------------------------
    # Item Offers
    # ---------------------------------------------------------------------------

    def list_item_offers(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostItemOffer]]:
        """List item offers with pagination support.

        GET /item-offers
        """
        url = self._build_url(GameBoostEndpoints.ITEM_OFFERS)

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                params=params,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            offers = [GameBoostItemOffer.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse item offers response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(offers, status_code=response.status_code, meta=meta)

    def get_item_offer(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOffer]:
        """Get a single item offer by ID."""
        return self._request(
            HttpMethod.GET,
            GameBoostEndpoints.item_offer(offer_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostItemOffer,
        )

    def create_item_offer(
        self,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOffer]:
        """Create a new item offer.

        POST /item-offers
        """
        return self._request(
            HttpMethod.POST,
            GameBoostEndpoints.ITEM_OFFERS,
            json_body=payload,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostItemOffer,
        )

    def update_item_offer(
        self,
        offer_id: str,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOffer]:
        """Update an existing item offer.

        PATCH /item-offers/{offer_id}
        """
        return self._request(
            HttpMethod.PATCH,
            GameBoostEndpoints.item_offer(offer_id),
            json_body=payload,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostItemOffer,
        )

    def list_item_offer_action(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOfferActionResponse]:
        """Publish (list) an item offer.

        POST /item-offers/{offer_id}/list  (no body)
        """
        return self._request_action(
            GameBoostEndpoints.item_offer_list_action(offer_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostItemOfferActionResponse,
        )

    def unlist_item_offer_action(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOfferActionResponse]:
        """Unlist (draft) an item offer.

        POST /item-offers/{offer_id}/draft  (no body)
        """
        return self._request_action(
            GameBoostEndpoints.item_offer_unlist_action(offer_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostItemOfferActionResponse,
        )

    def archive_item_offer_action(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOfferActionResponse]:
        """Archive an item offer.

        POST /item-offers/{offer_id}/archive  (no body)
        """
        return self._request_action(
            GameBoostEndpoints.item_offer_archive_action(offer_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostItemOfferActionResponse,
        )

    def get_item_offer_template(
        self,
        game_slug: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOfferTemplate]:
        """Get item offer creation template for a game.

        GET /item-offers/templates/{game_slug}
        """
        url = self._build_url(GameBoostEndpoints.item_offer_template(game_slug))

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            data = body.get("template", body) if isinstance(body, dict) else body
            parsed = GameBoostItemOfferTemplate.model_validate(data)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse item offer template response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(parsed, status_code=response.status_code, meta=meta)

    def list_item_offer_orders(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostItemOrder]]:
        """List orders for a specific item offer.

        GET /item-offers/{offer_id}/orders
        """
        url = self._build_url(GameBoostEndpoints.item_offer_orders(offer_id))

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                params=params,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            orders = [GameBoostItemOrder.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse item offer orders response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(orders, status_code=response.status_code, meta=meta)

    # ---------------------------------------------------------------------------
    # Item Orders
    # ---------------------------------------------------------------------------

    def list_item_orders(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostItemOrder]]:
        """List item orders with pagination support.

        GET /item-orders
        """
        url = self._build_url(GameBoostEndpoints.ITEM_ORDERS)

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                params=params,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            orders = [GameBoostItemOrder.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse item orders response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(orders, status_code=response.status_code, meta=meta)

    def get_item_order(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOrder]:
        """Get a single item order by ID."""
        return self._request(
            HttpMethod.GET,
            GameBoostEndpoints.item_order(order_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostItemOrder,
        )

    def complete_item_order(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostItemOrderActionResponse]:
        """Complete an item order.

        POST /item-orders/{order_id}/complete  (no body)
        """
        return self._request_action(
            GameBoostEndpoints.item_order_complete(order_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostItemOrderActionResponse,
        )

    def list_item_order_messages(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostMessage]]:
        """List messages for an item order.

        GET /item-orders/{order_id}/messages
        """
        url = self._build_url(GameBoostEndpoints.item_order_messages(order_id))

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            messages = [GameBoostMessage.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse item order messages response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(messages, status_code=response.status_code, meta=meta)

    def send_item_order_message(
        self,
        order_id: str,
        message: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostMessage]:
        """Send a message to an item order.

        POST /item-orders/{order_id}/messages
        Body: {"message": "..."}  (max 10,000 chars)
        """
        url = self._build_url(GameBoostEndpoints.item_order_messages(order_id))

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=auth_headers,
                json_body={"message": message},
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            data = body.get("data", body) if isinstance(body, dict) else body
            parsed = GameBoostMessage.model_validate(data)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse send item order message response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(parsed, status_code=response.status_code, meta=meta)

    # ---------------------------------------------------------------------------
    # Gift Card Catalog
    # ---------------------------------------------------------------------------

    def list_gift_cards(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostGiftCard]]:
        """List gift card catalog entries with pagination.

        GET /gift-cards
        """
        url = self._build_url(GameBoostEndpoints.GIFT_CARDS)

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                params=params,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            cards = [GameBoostGiftCard.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse gift cards response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(cards, status_code=response.status_code, meta=meta)

    def get_gift_card(
        self,
        gift_card_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostGiftCard]:
        """Get a single gift card catalog entry by ID."""
        return self._request(
            HttpMethod.GET,
            GameBoostEndpoints.gift_card(gift_card_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostGiftCard,
        )

    def list_gift_card_brands(
        self,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostGiftCardBrand]]:
        """List all gift card brands.

        GET /gift-cards/brands
        """
        url = self._build_url(GameBoostEndpoints.GIFT_CARD_BRANDS)

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            brands = [GameBoostGiftCardBrand.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse gift card brands response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(brands, status_code=response.status_code, meta=meta)

    def list_gift_card_regions(
        self,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostGiftCardRegion]]:
        """List all gift card regions.

        GET /gift-cards/regions
        """
        url = self._build_url(GameBoostEndpoints.GIFT_CARD_REGIONS)

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            regions = [GameBoostGiftCardRegion.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse gift card regions response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(regions, status_code=response.status_code, meta=meta)

    # ---------------------------------------------------------------------------
    # Gift Card Offers
    # ---------------------------------------------------------------------------

    def list_gift_card_offers(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostGiftCardOffer]]:
        """List gift card offers with pagination.

        GET /gift-cards/offers
        """
        url = self._build_url(GameBoostEndpoints.GIFT_CARD_OFFERS)

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                params=params,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            offers = [GameBoostGiftCardOffer.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse gift card offers response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(offers, status_code=response.status_code, meta=meta)

    def get_gift_card_offer(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostGiftCardOffer]:
        """Get a single gift card offer by ID."""
        return self._request(
            HttpMethod.GET,
            GameBoostEndpoints.gift_card_offer(offer_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostGiftCardOffer,
        )

    def create_gift_card_offer(
        self,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostGiftCardOffer]:
        """Create a new gift card offer.

        POST /gift-cards/offers
        Body: {gift_card_id?, brand_id?, region_id?, face_value_amount?, face_value_unit?, price, keys?}
        """
        return self._request(
            HttpMethod.POST,
            GameBoostEndpoints.GIFT_CARD_OFFERS,
            json_body=payload,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostGiftCardOffer,
        )

    def update_gift_card_offer(
        self,
        offer_id: str,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostGiftCardOffer]:
        """Update a gift card offer (price only).

        PATCH /gift-cards/offers/{offer_id}
        Body: {price}
        """
        return self._request(
            HttpMethod.PATCH,
            GameBoostEndpoints.gift_card_offer(offer_id),
            json_body=payload,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostGiftCardOffer,
        )

    def delete_gift_card_offer(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[None]:
        """Delete a gift card offer.

        DELETE /gift-cards/offers/{offer_id}
        """
        return self._request(
            HttpMethod.DELETE,
            GameBoostEndpoints.gift_card_offer(offer_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=None,
        )

    def add_gift_card_offer_stock(
        self,
        offer_id: str,
        keys: list[str],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostGiftCardAddStockResponse]:
        """Add stock (keys) to a gift card offer.

        POST /gift-cards/offers/{offer_id}/stock
        Body: {"keys": ["key1", "key2", ...]}
        """
        url = self._build_url(GameBoostEndpoints.gift_card_offer_stock(offer_id))

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=auth_headers,
                json_body={"keys": keys},
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            parsed = GameBoostGiftCardAddStockResponse.model_validate(body)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse add gift card stock response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(parsed, status_code=response.status_code, meta=meta)

    def remove_gift_card_offer_stock_item(
        self,
        offer_id: str,
        delivery_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[None]:
        """Remove a single stock item from a gift card offer.

        DELETE /gift-cards/offers/{offer_id}/stock/{delivery_id}
        """
        return self._request(
            HttpMethod.DELETE,
            GameBoostEndpoints.gift_card_offer_stock_item(offer_id, delivery_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=None,
        )

    # ---------------------------------------------------------------------------
    # Gift Card Orders
    # ---------------------------------------------------------------------------

    def list_gift_card_orders(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostGiftCardOrder]]:
        """List gift card orders with pagination.

        GET /gift-card-orders
        """
        url = self._build_url(GameBoostEndpoints.GIFT_CARD_ORDERS)

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                params=params,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            orders = [GameBoostGiftCardOrder.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse gift card orders response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(orders, status_code=response.status_code, meta=meta)

    def get_gift_card_order(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostGiftCardOrder]:
        """Get a single gift card order by ID."""
        return self._request(
            HttpMethod.GET,
            GameBoostEndpoints.gift_card_order(order_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostGiftCardOrder,
        )

    # ---------------------------------------------------------------------------
    # Currency Offers
    # ---------------------------------------------------------------------------

    def list_currency_offers(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostCurrencyOffer]]:
        """List currency offers with pagination.

        GET /currency-offers
        """
        url = self._build_url(GameBoostEndpoints.CURRENCY_OFFERS)

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                params=params,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            offers = [GameBoostCurrencyOffer.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse currency offers response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(offers, status_code=response.status_code, meta=meta)

    def get_currency_offer(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOffer]:
        """Get a single currency offer by ID."""
        return self._request(
            HttpMethod.GET,
            GameBoostEndpoints.currency_offer(offer_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostCurrencyOffer,
        )

    def create_currency_offer(
        self,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOffer]:
        """Create a new currency offer.

        POST /currency-offers
        """
        return self._request(
            HttpMethod.POST,
            GameBoostEndpoints.CURRENCY_OFFERS,
            json_body=payload,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostCurrencyOffer,
        )

    def update_currency_offer(
        self,
        offer_id: str,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOffer]:
        """Update an existing currency offer.

        PATCH /currency-offers/{offer_id}
        """
        return self._request(
            HttpMethod.PATCH,
            GameBoostEndpoints.currency_offer(offer_id),
            json_body=payload,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostCurrencyOffer,
        )

    def list_currency_offer_action(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOfferActionResponse]:
        """Publish (list) a currency offer.

        POST /currency-offers/{offer_id}/list  (no body)
        """
        return self._request_action(
            GameBoostEndpoints.currency_offer_list_action(offer_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostCurrencyOfferActionResponse,
        )

    def unlist_currency_offer_action(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOfferActionResponse]:
        """Unlist (draft) a currency offer.

        POST /currency-offers/{offer_id}/draft  (no body)
        """
        return self._request_action(
            GameBoostEndpoints.currency_offer_unlist_action(offer_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostCurrencyOfferActionResponse,
        )

    def archive_currency_offer_action(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOfferActionResponse]:
        """Archive a currency offer.

        POST /currency-offers/{offer_id}/archive  (no body)
        """
        return self._request_action(
            GameBoostEndpoints.currency_offer_archive_action(offer_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostCurrencyOfferActionResponse,
        )

    def get_currency_offer_template(
        self,
        game_slug: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOfferTemplate]:
        """Get currency offer creation template for a game.

        GET /currency-offers/templates/{game_slug}
        """
        url = self._build_url(GameBoostEndpoints.currency_offer_template(game_slug))

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            data = body.get("template", body) if isinstance(body, dict) else body
            parsed = GameBoostCurrencyOfferTemplate.model_validate(data)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse currency offer template response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(parsed, status_code=response.status_code, meta=meta)

    def list_currency_offer_orders(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostCurrencyOrder]]:
        """List orders for a specific currency offer.

        GET /currency-offers/{offer_id}/orders
        """
        url = self._build_url(GameBoostEndpoints.currency_offer_orders(offer_id))

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                params=params,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            orders = [GameBoostCurrencyOrder.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse currency offer orders response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(orders, status_code=response.status_code, meta=meta)

    # ---------------------------------------------------------------------------
    # Currency Orders
    # ---------------------------------------------------------------------------

    def list_currency_orders(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostCurrencyOrder]]:
        """List currency orders with pagination.

        GET /currency-orders
        """
        url = self._build_url(GameBoostEndpoints.CURRENCY_ORDERS)

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                params=params,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            orders = [GameBoostCurrencyOrder.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse currency orders response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(orders, status_code=response.status_code, meta=meta)

    def get_currency_order(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOrder]:
        """Get a single currency order by ID."""
        return self._request(
            HttpMethod.GET,
            GameBoostEndpoints.currency_order(order_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostCurrencyOrder,
        )

    def complete_currency_order(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostCurrencyOrderActionResponse]:
        """Complete a currency order.

        POST /currency-orders/{order_id}/complete  (no body)
        """
        return self._request_action(
            GameBoostEndpoints.currency_order_complete(order_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=GameBoostCurrencyOrderActionResponse,
        )

    def list_currency_order_messages(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[list[GameBoostMessage]]:
        """List messages for a currency order.

        GET /currency-orders/{order_id}/messages
        """
        url = self._build_url(GameBoostEndpoints.currency_order_messages(order_id))

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            items = GameBoostMapper.extract_list_data(body)
            messages = [GameBoostMessage.model_validate(item) for item in items]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse currency order messages response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(messages, status_code=response.status_code, meta=meta)

    def send_currency_order_message(
        self,
        order_id: str,
        message: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[GameBoostMessage]:
        """Send a message to a currency order.

        POST /currency-orders/{order_id}/messages
        Body: {"message": "..."}  (max 10,000 chars)
        """
        url = self._build_url(GameBoostEndpoints.currency_order_messages(order_id))

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=auth_headers,
                json_body={"message": message},
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            data = body.get("data", body) if isinstance(body, dict) else body
            parsed = GameBoostMessage.model_validate(data)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse send currency order message response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(parsed, status_code=response.status_code, meta=meta)

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    def _request(
        self,
        method: HttpMethod,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
        response_type: type | None = None,
    ) -> ApiResult[Any]:
        """Generic authenticated request helper."""
        url = self._build_url(path)

        try:
            response = self._transport.request(
                method,
                url,
                headers=auth_headers,
                json_body=json_body,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        if response_type is None:
            return ApiResult.success(None, status_code=response.status_code)

        try:
            body = response.json()
            # GameBoost may wrap single-item responses in a "data" key
            data = body.get("data", body) if isinstance(body, dict) else body
            parsed = response_type.model_validate(data)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(parsed, status_code=response.status_code, meta=meta)

    def _request_action(
        self,
        path: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
        response_type: type,
    ) -> ApiResult[Any]:
        """POST action helper for body-less state transitions (list/unlist/archive/complete).

        These endpoints return full response body (not just data wrapper).
        """
        url = self._build_url(path)

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=auth_headers,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            parsed = response_type.model_validate(body)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse action response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response, body)
        return ApiResult.success(parsed, status_code=response.status_code, meta=meta)

    def _extract_meta(self, response: Any, body: Any = None) -> dict[str, object]:
        """Extract metadata (request-id, rate-limit, pagination) from response."""
        meta: dict[str, object] = {}

        request_id = GameBoostMapper.extract_request_id(response.headers, body)
        if request_id:
            meta["request_id"] = request_id

        rate_limit = GameBoostMapper.extract_rate_limit_meta(response.headers)
        meta.update(rate_limit)

        pagination = GameBoostMapper.extract_pagination_meta(body)
        if pagination:
            meta["pagination"] = pagination.model_dump()

        return meta

    def _handle_error(self, status_code: int, response: Any) -> ApiResult[Any]:
        """Map HTTP error codes to SDK error categories.

        GameBoost-specific: 407 (Proxy Authentication Required) is treated
        as a retryable network error to allow proxy rotation.
        """
        category_map: dict[int, ErrorCategory] = {
            400: ErrorCategory.VALIDATION,
            401: ErrorCategory.AUTHENTICATION,
            403: ErrorCategory.AUTHENTICATION,
            404: ErrorCategory.NOT_FOUND,
            407: ErrorCategory.NETWORK,
            409: ErrorCategory.CONFLICT,
            422: ErrorCategory.VALIDATION,
            429: ErrorCategory.RATE_LIMIT,
        }

        category = category_map.get(status_code, ErrorCategory.SERVER_ERROR)
        is_retryable = status_code >= 500 or status_code == 429 or status_code == 407

        retry_after: float | None = None
        if status_code == 429:
            try:
                retry_after = float(response.headers.get("Retry-After", 5))
            except (ValueError, TypeError, AttributeError):
                retry_after = 5.0

        try:
            body = response.json() if hasattr(response, "json") else {}
            message = str(
                body.get("message", body.get("error", f"HTTP {status_code}"))
            )
        except Exception:
            message = f"HTTP {status_code}"

        return ApiResult.from_error(
            category,
            message,
            status_code=status_code,
            provider=self.PROVIDER,
            retry_after=retry_after,
            is_retryable=is_retryable,
        )
