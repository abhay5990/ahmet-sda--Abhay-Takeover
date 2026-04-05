"""
Low-level G2G API client.

Handles raw HTTP communication with the G2G API.
Returns parsed response models with extracted metadata.
The facade layer handles auth header injection, proxy selection,
retry orchestration, and per-instance throttling.

G2G responses use an internal envelope:
  {"code": 2000, "payload": {...}, "messages": [...]}

The client unwraps this envelope and maps G2G-internal codes
to SDK error categories.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.clients.marketplaces.g2g.config import G2GConfig
from apis_sdk.clients.marketplaces.g2g.endpoints import G2GEndpoints
from apis_sdk.clients.marketplaces.g2g.models import G2GEnvelope, G2GOffer


class G2GClient:
    """
    Low-level G2G API client.

    Handles:
    - Request execution via injected transport
    - G2G response envelope unwrapping
    - Response parsing into G2G-specific models
    - Error categorization from HTTP status and G2G envelope codes

    Does NOT handle:
    - Authentication (injected via auth_headers parameter)
    - Retry logic (handled by facade/retry policy)
    - Proxy selection (handled by proxy pool)
    - Rate limiting / throttling (handled by facade)
    """

    PROVIDER = "g2g"

    def __init__(
        self,
        config: G2GConfig,
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
    ) -> ApiResult[dict[str, Any]]:
        """
        Create a new offer on G2G.

        Accepts a raw payload dict - game-specific payload building
        is out of scope for the SDK.

        Returns the raw G2G envelope payload on success.
        """
        return self._request(
            HttpMethod.POST,
            G2GEndpoints.CREATE_OFFER,
            json_body=payload,
            params={"v": "v2"},
            auth_headers=auth_headers,
            proxy_url=proxy_url,
        )

    def update_offer(
        self,
        offer_id: str,
        payload: dict[str, Any],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Update an existing offer."""
        return self._request(
            HttpMethod.PUT,
            G2GEndpoints.offer(offer_id),
            json_body=payload,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
        )

    def delete_offer(
        self,
        offer_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[None]:
        """Delete an offer."""
        url = self._build_url(G2GEndpoints.offer(offer_id))

        try:
            response = self._transport.request(
                HttpMethod.DELETE,
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

        return ApiResult.success(None, status_code=response.status_code)

    def get_offers(
        self,
        *,
        auth_headers: dict[str, str],
        page: int = 1,
        page_size: int = 20,
        status: str = "active",
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """
        List seller's offers with pagination.

        Uses seller_id from config in the URL path.
        Returns the raw G2G envelope payload on success.
        """
        path = G2GEndpoints.my_offers(self._config.seller_id)
        params = {
            "page": str(page),
            "page_size": str(page_size),
            "status": status,
        }
        return self._request(
            HttpMethod.GET,
            path,
            params=params,
            auth_headers=auth_headers,
            proxy_url=proxy_url,
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
        params: dict[str, Any] | None = None,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[Any]:
        """Generic authenticated request helper with envelope unwrapping."""
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
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        # Parse and unwrap G2G envelope
        try:
            body = response.json()
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse G2G response: {exc}",
                provider=self.PROVIDER,
            )

        # G2G wraps responses in {"code": ..., "payload": ..., "messages": [...]}
        if isinstance(body, dict) and "payload" in body:
            envelope = G2GEnvelope.model_validate(body)
            return ApiResult.success(
                envelope.payload,
                status_code=response.status_code,
                meta={"g2g_code": envelope.code},
            )

        # If no envelope structure, return body as-is
        return ApiResult.success(body, status_code=response.status_code)

    def _handle_error(self, status_code: int, response: Any) -> ApiResult[Any]:
        """Map HTTP error codes to SDK error categories.

        Also attempts to extract error details from the G2G envelope.
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

        # Try to extract message from G2G envelope
        message = f"HTTP {status_code}"
        try:
            body = response.json() if hasattr(response, "json") else {}
            if isinstance(body, dict):
                messages = body.get("messages", [])
                if messages and isinstance(messages, list):
                    first = messages[0]
                    if isinstance(first, dict):
                        message = first.get("text", message)
                if message == f"HTTP {status_code}":
                    message = str(body.get("message", message))
        except Exception:
            pass

        return ApiResult.from_error(
            category,
            message,
            status_code=status_code,
            provider=self.PROVIDER,
            retry_after=retry_after,
            is_retryable=is_retryable,
        )
