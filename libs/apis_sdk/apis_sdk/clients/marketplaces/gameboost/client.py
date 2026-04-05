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
    GameBoostAddCredentialsResponse,
    GameBoostBulkDeleteCredentialsResponse,
    GameBoostCredentialEntry,
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
