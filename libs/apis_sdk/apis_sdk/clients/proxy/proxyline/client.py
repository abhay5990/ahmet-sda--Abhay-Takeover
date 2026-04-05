"""
Low-level Proxyline API client.

Handles raw HTTP communication with the Proxyline API.
Returns parsed response models, not SDK-canonical types.
The facade layer handles mapping and error normalization.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.clients.proxy.proxyline.config import ProxylineConfig
from apis_sdk.clients.proxy.proxyline.endpoints import ProxylineEndpoints
from apis_sdk.clients.proxy.proxyline.models import (
    ProxylineBalance,
    ProxylineListResponse,
    ProxylineOrder,
    ProxylineProxy,
)


class ProxylineClient:
    """
    Low-level Proxyline API client.

    Handles:
    - Authentication (API key in query params)
    - Request execution via injected transport
    - Response parsing into Proxyline-specific models
    - Error categorization

    Does NOT handle:
    - Mapping to SDK canonical models (that's the mapper's job)
    - Retry logic (that's the retry policy's job)
    - Proxy pool management (that's the infrastructure's job)
    """

    PROVIDER = "proxyline"

    def __init__(
        self,
        config: ProxylineConfig,
        transport: BaseHttpTransport,
        *,
        logger: SdkLogger | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._logger = logger or NullLogger()

    def _build_url(self, path: str) -> str:
        return f"{self._config.base_url}{path}"

    def _auth_params(self) -> dict[str, str]:
        return {"api_key": self._config.api_key}

    def list_proxies(self) -> ApiResult[list[ProxylineProxy]]:
        """Fetch all proxies from the Proxyline API."""
        url = self._build_url(ProxylineEndpoints.PROXIES)

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                params=self._auth_params(),
                timeout=self._config.timeout,
            )
        except TransportError as exc:
            self._logger.error("Proxyline API request failed", error=str(exc))
            return ApiResult.from_error(
                ErrorCategory.NETWORK,
                str(exc),
                provider=self.PROVIDER,
                is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error_response(response.status_code, response)

        try:
            data = response.json()
            if isinstance(data, list):
                proxies = [ProxylineProxy.model_validate(item) for item in data]
            else:
                parsed = ProxylineListResponse.model_validate(data)
                proxies = parsed.results
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse Proxyline response: {exc}",
                provider=self.PROVIDER,
            )

        self._logger.info("Fetched proxies from Proxyline", count=len(proxies))
        return ApiResult.success(proxies, status_code=response.status_code)

    def get_balance(self) -> ApiResult[ProxylineBalance]:
        """Fetch account balance from Proxyline."""
        url = self._build_url(ProxylineEndpoints.BALANCE)

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                params=self._auth_params(),
                timeout=self._config.timeout,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK,
                str(exc),
                provider=self.PROVIDER,
                is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error_response(response.status_code, response)

        try:
            balance = ProxylineBalance.model_validate(response.json())
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse balance response: {exc}",
                provider=self.PROVIDER,
            )

        return ApiResult.success(balance, status_code=response.status_code)

    def get_orders(self) -> ApiResult[list[ProxylineOrder]]:
        """Fetch active proxy orders/subscriptions."""
        url = self._build_url(ProxylineEndpoints.ORDERS)

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                params=self._auth_params(),
                timeout=self._config.timeout,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK,
                str(exc),
                provider=self.PROVIDER,
                is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error_response(response.status_code, response)

        try:
            data = response.json()
            if isinstance(data, list):
                orders = [ProxylineOrder.model_validate(item) for item in data]
            else:
                orders = [ProxylineOrder.model_validate(item) for item in data.get("results", [])]
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse orders response: {exc}",
                provider=self.PROVIDER,
            )

        return ApiResult.success(orders, status_code=response.status_code)

    def _handle_error_response(
        self, status_code: int, response: Any
    ) -> ApiResult[Any]:
        """Map HTTP error codes to SDK error categories."""
        category_map: dict[int, ErrorCategory] = {
            401: ErrorCategory.AUTHENTICATION,
            403: ErrorCategory.AUTHENTICATION,
            404: ErrorCategory.NOT_FOUND,
            429: ErrorCategory.RATE_LIMIT,
        }

        category = category_map.get(status_code, ErrorCategory.SERVER_ERROR)
        is_retryable = status_code >= 500 or status_code == 429

        try:
            body = response.json() if hasattr(response, "json") else {}
            message = body.get("detail", body.get("error", f"HTTP {status_code}"))
        except Exception:
            message = f"HTTP {status_code}"

        retry_after: float | None = None
        if status_code == 429:
            try:
                retry_after = float(response.headers.get("Retry-After", 5))
            except (ValueError, TypeError, AttributeError):
                retry_after = 5.0

        return ApiResult.from_error(
            category,
            message,
            status_code=status_code,
            provider=self.PROVIDER,
            is_retryable=is_retryable,
            retry_after=retry_after,
        )
