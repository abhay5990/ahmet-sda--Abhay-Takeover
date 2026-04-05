"""
Low-level RBXCrate API client.

Handles raw HTTP communication with the RBXCrate API.
Returns ApiResult with raw dicts — response shapes are simple
and stable enough that dedicated models are not yet warranted.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.clients.services.rbxcrate.config import RbxCrateConfig
from apis_sdk.clients.services.rbxcrate.endpoints import RbxCrateEndpoints


class RbxCrateClient:
    """
    Low-level RBXCrate API client.

    Handles:
    - Request execution via injected transport
    - Response parsing (raw JSON dicts)
    - Error categorization

    Does NOT handle:
    - Authentication (injected via auth_headers parameter)
    - Retry logic (deferred — may be added at facade level later)
    """

    PROVIDER = "rbxcrate"

    def __init__(
        self,
        config: RbxCrateConfig,
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
    # Stock
    # ---------------------------------------------------------------------------

    def get_stock(
        self,
        *,
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]:
        """Fetch current Robux stock."""
        return self._get(RbxCrateEndpoints.STOCK, auth_headers=auth_headers)

    def get_detailed_stock(
        self,
        *,
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]:
        """Fetch detailed Robux stock information."""
        return self._get(RbxCrateEndpoints.DETAILED_STOCK, auth_headers=auth_headers)

    # ---------------------------------------------------------------------------
    # Order info
    # ---------------------------------------------------------------------------

    def get_order_info(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]:
        """Query order status and details."""
        return self._post(
            RbxCrateEndpoints.ORDER_INFO,
            json_body={"orderId": order_id},
            auth_headers=auth_headers,
        )

    # ---------------------------------------------------------------------------
    # Order management (writes)
    # ---------------------------------------------------------------------------

    def cancel_order(
        self,
        order_id: str,
        *,
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]:
        """Cancel an order (only Error/Queued status orders can be cancelled)."""
        return self._post(
            RbxCrateEndpoints.ORDER_CANCEL,
            json_body={"orderId": order_id},
            auth_headers=auth_headers,
        )

    def create_gamepass_order(
        self,
        *,
        order_id: str,
        roblox_username: str,
        robux_amount: int,
        place_id: int,
        is_pre_order: bool = True,
        check_ownership: bool = False,
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]:
        """Create a new gamepass order."""
        payload = {
            "orderId": order_id,
            "robloxUsername": roblox_username,
            "robuxAmount": robux_amount,
            "placeId": place_id,
            "isPreOrder": is_pre_order,
            "checkOwnership": check_ownership,
        }
        return self._post(
            RbxCrateEndpoints.GAMEPASS_ORDER,
            json_body=payload,
            auth_headers=auth_headers,
        )

    def resend_gamepass_order(
        self,
        *,
        order_id: str,
        place_id: int,
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]:
        """Retry a failed gamepass order (possibly with a new place ID)."""
        payload = {
            "orderId": order_id,
            "placeId": place_id,
        }
        return self._post(
            RbxCrateEndpoints.GAMEPASS_RESEND,
            json_body=payload,
            auth_headers=auth_headers,
        )

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    def _get(
        self,
        path: str,
        *,
        auth_headers: dict[str, str],
        params: dict[str, Any] | None = None,
    ) -> ApiResult[dict[str, Any]]:
        url = self._build_url(path)
        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
                params=params,
                timeout=self._config.timeout,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )
        return self._handle_response(response)

    def _post(
        self,
        path: str,
        *,
        json_body: dict[str, Any],
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]:
        url = self._build_url(path)
        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=auth_headers,
                json_body=json_body,
                timeout=self._config.timeout,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )
        return self._handle_response(response)

    def _handle_response(self, response: Any) -> ApiResult[dict[str, Any]]:
        """Parse a successful or error response into ApiResult."""
        if response.is_success:
            try:
                body = response.json()
            except Exception as exc:
                return ApiResult.from_error(
                    ErrorCategory.UNKNOWN,
                    f"Failed to parse response: {exc}",
                    provider=self.PROVIDER,
                )
            return ApiResult.success(body, status_code=response.status_code)

        return self._handle_error(response.status_code, response)

    def _handle_error(self, status_code: int, response: Any) -> ApiResult[Any]:
        """Map HTTP error codes to SDK error categories."""
        message = f"HTTP {status_code}"
        details: dict[str, Any] = {}

        try:
            body = response.json() if hasattr(response, "json") else {}
            if isinstance(body, dict):
                msg = body.get("message") or body.get("error")
                if msg:
                    message = str(msg)
                    details["body"] = body
        except Exception:
            pass

        category_map: dict[int, ErrorCategory] = {
            400: ErrorCategory.VALIDATION,
            401: ErrorCategory.AUTHENTICATION,
            403: ErrorCategory.AUTHENTICATION,
            404: ErrorCategory.NOT_FOUND,
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

        return ApiResult.from_error(
            category,
            message,
            status_code=status_code,
            provider=self.PROVIDER,
            retry_after=retry_after,
            is_retryable=is_retryable,
            details=details,
        )
