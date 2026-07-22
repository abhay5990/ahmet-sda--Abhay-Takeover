"""
Low-level Eldorado API client.

Handles raw HTTP communication with the Eldorado API.
Returns parsed response models, not SDK-canonical types.
The facade layer handles mapping, auth header injection, and error normalization.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.clients.marketplaces.eldorado.config import EldoradoConfig
from apis_sdk.clients.marketplaces.eldorado.endpoints import EldoradoEndpoints
from apis_sdk.clients.marketplaces.eldorado.models import (
    EldoradoNotificationsPage,
    EldoradoOffer,
    EldoradoOfferCredentialsResponse,
    EldoradoOfferSearchItem,
    EldoradoOfferSearchPage,
    EldoradoOfferStateCount,
    EldoradoOrder,
    EldoradoOrderAccountDetails,
    EldoradoReviewsResponse,
    EldoradoSellerOrdersPage,
)


class EldoradoClient:
    """
    Low-level Eldorado API client.

    Handles:
    - Request execution via injected transport
    - Response parsing into Eldorado-specific models
    - Error categorization

    Does NOT handle:
    - Authentication (injected via auth_headers parameter)
    - Retry logic (handled by retry policy)
    - Proxy selection (handled by proxy pool)
    - Mapping to SDK canonical models (handled by mapper)
    """

    PROVIDER = "eldorado"

    def __init__(
        self,
        config: EldoradoConfig,
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
    # Offers
    # ---------------------------------------------------------------------------

    def create_offer(
        self,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoOfferSearchItem]:
        """Create a new offer on Eldorado.

        The create endpoint returns a flat structure matching
        EldoradoOfferSearchItem, not the nested EldoradoOffer layout.
        """
        return self._request(
            HttpMethod.POST,
            EldoradoEndpoints.CREATE_OFFER,
            json_body=payload,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=EldoradoOfferSearchItem,
        )

    def update_offer(
        self,
        offer_id: str,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoOffer]:
        """Update an existing offer on Eldorado."""
        return self._request(
            HttpMethod.PUT,
            EldoradoEndpoints.offer(offer_id),
            json_body=payload,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=EldoradoOffer,
        )

    def delete_offer(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[None]:
        """Delete an offer from Eldorado."""
        return self._request(
            HttpMethod.DELETE,
            EldoradoEndpoints.delete_offer(offer_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=None,
        )

    def search_my_offers(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoOfferSearchPage]:
        """Search seller's own offers (paginated)."""
        return self._request(
            HttpMethod.GET,
            EldoradoEndpoints.SEARCH_MY_OFFERS,
            auth_headers=auth_headers,
            params=params,
            proxy_url=proxy_url,
            response_type=EldoradoOfferSearchPage,
        )

    # ---------------------------------------------------------------------------
    # Orders
    # ---------------------------------------------------------------------------

    def get_seller_orders(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoSellerOrdersPage]:
        """Fetch a paginated page of seller orders."""
        return self._request(
            HttpMethod.GET,
            EldoradoEndpoints.MY_SELLER_ORDERS,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=EldoradoSellerOrdersPage,
            params=params,
        )

    def get_order_by_id(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoOrder]:
        """Fetch a single order by its ID."""
        return self._request(
            HttpMethod.GET,
            EldoradoEndpoints.order_by_id(order_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=EldoradoOrder,
        )

    def deliver_order(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[None]:
        """Mark an order as delivered. PUT with empty JSON body."""
        return self._request(
            HttpMethod.PUT,
            EldoradoEndpoints.deliver_order(order_id),
            json_body={},
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=None,
        )

    def get_offer_state_counts(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoOfferStateCount]:
        """Fetch offer state counts (active, paused, closed, offline)."""
        return self._request(
            HttpMethod.GET,
            EldoradoEndpoints.OFFER_STATE_COUNTS,
            auth_headers=auth_headers,
            params=params,
            proxy_url=proxy_url,
            response_type=EldoradoOfferStateCount,
        )

    def get_order_account_details(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoOrderAccountDetails]:
        """Fetch account/credential details for a completed order."""
        return self._request(
            HttpMethod.GET,
            EldoradoEndpoints.order_details(order_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=EldoradoOrderAccountDetails,
        )

    def get_offer_account_details(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoOfferCredentialsResponse]:
        """Fetch credential details for an offer (by offer ID)."""
        return self._request(
            HttpMethod.GET,
            EldoradoEndpoints.offer_details(offer_id),
            auth_headers=auth_headers,
            proxy_url=proxy_url,
            response_type=EldoradoOfferCredentialsResponse,
        )

    # ---------------------------------------------------------------------------
    # Reviews
    # ---------------------------------------------------------------------------

    def get_seller_reviews(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoReviewsResponse]:
        """Fetch paginated seller reviews."""
        return self._request(
            HttpMethod.GET,
            EldoradoEndpoints.SELLER_REVIEWS,
            auth_headers=auth_headers,
            params=params,
            proxy_url=proxy_url,
            response_type=EldoradoReviewsResponse,
        )

    # ---------------------------------------------------------------------------
    # Notifications
    # ---------------------------------------------------------------------------

    def get_notifications(
        self,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
        proxy_url: str | None = None,
    ) -> ApiResult[EldoradoNotificationsPage]:
        """Fetch paginated notifications for the authenticated user."""
        return self._request(
            HttpMethod.GET,
            EldoradoEndpoints.NOTIFICATIONS_ME,
            auth_headers=auth_headers,
            params=params,
            proxy_url=proxy_url,
            response_type=EldoradoNotificationsPage,
        )

    # ---------------------------------------------------------------------------
    # Image Upload
    # ---------------------------------------------------------------------------

    def upload_image(
        self,
        file_path: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[list[str]]:
        """
        Upload an image to Eldorado.

        Returns a list of S3 keys (small, large, original).
        """
        url = self._build_url(EldoradoEndpoints.UPLOAD_IMAGE)

        try:
            with open(file_path, "rb") as f:
                response = self._transport.request(
                    HttpMethod.POST,
                    url,
                    headers=auth_headers,
                    files={"image": (Path(file_path).name, f, "image/png")},
                    timeout=self._config.timeout,
                    proxy_url=proxy_url,
                )
        except FileNotFoundError:
            return ApiResult.from_error(
                ErrorCategory.VALIDATION,
                f"Image file not found: {file_path}",
                provider=self.PROVIDER,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK,
                str(exc),
                provider=self.PROVIDER,
                is_retryable=True,
                details=exc.details,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            data = response.json()
            local_paths = data if isinstance(data, list) else data.get("localPaths", [])
            paths = [p.replace("/offerimages/", "") for p in local_paths]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse upload response: {exc}",
                provider=self.PROVIDER,
            )

        return ApiResult.success(paths, status_code=response.status_code)

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    def _request(
        self,
        method: HttpMethod,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
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
                params=params,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK,
                str(exc),
                provider=self.PROVIDER,
                is_retryable=True,
                details=exc.details,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        if response_type is None:
            return ApiResult.success(None, status_code=response.status_code)

        try:
            parsed = response_type.model_validate(response.json())
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse response: {exc}",
                provider=self.PROVIDER,
            )

        return ApiResult.success(parsed, status_code=response.status_code)

    def _handle_error(self, status_code: int, response: Any) -> ApiResult[Any]:
        """Map HTTP error codes to SDK error categories."""
        category_map: dict[int, ErrorCategory] = {
            400: ErrorCategory.VALIDATION,
            401: ErrorCategory.AUTHENTICATION,
            403: ErrorCategory.AUTHENTICATION,
            404: ErrorCategory.NOT_FOUND,
            409: ErrorCategory.CONFLICT,
            422: ErrorCategory.VALIDATION,
            429: ErrorCategory.RATE_LIMIT,
        }

        category = category_map.get(status_code, ErrorCategory.SERVER_ERROR)
        is_retryable = status_code >= 500 or status_code == 429

        retry_after: float | None = None
        if status_code == 429:
            try:
                retry_after = float(response.headers.get("Retry-After", 5))
            except (ValueError, TypeError, AttributeError):
                retry_after = 5.0

        body: dict = {}
        try:
            body = response.json() if hasattr(response, "json") else {}
            message = str(body.get("message", body.get("error", f"HTTP {status_code}")))
        except Exception:
            # Fallback: try raw text
            raw_text = getattr(response, 'text', '') or ''
            message = raw_text[:500] if raw_text else f"HTTP {status_code}"

        # Detect password lockout from Cognito (mirrors legacy behavior)
        if "password attempts exceeded" in message.lower():
            is_retryable = True
            category = ErrorCategory.AUTHENTICATION

        return ApiResult.from_error(
            category,
            message,
            status_code=status_code,
            provider=self.PROVIDER,
            retry_after=retry_after,
            is_retryable=is_retryable,
            details=body if body else None,
        )
