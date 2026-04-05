"""
Low-level LZT Market API client.

Handles raw HTTP communication with the LZT Market API.
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
from apis_sdk.clients.marketplaces.lzt.config import LztConfig
from apis_sdk.clients.marketplaces.lzt.endpoints import LztEndpoints
from apis_sdk.clients.marketplaces.lzt.models import (
    LztCheckAccountResult,
    LztListingPage,
    LztOrderPage,
    LztPurchaseResult,
)


class LztClient:
    """
    Low-level LZT Market API client.

    Handles:
    - Request execution via injected transport
    - Response parsing into LZT-specific models
    - Error categorization (including 403 account-deleted detection)
    - Metadata extraction

    Does NOT handle:
    - Authentication (injected via auth_headers parameter)
    - Retry logic (handled by facade/retry policy)
    - Proxy selection (handled by proxy pool)
    - Rate limiting (handled by facade pre_execute hook)
    """

    PROVIDER = "lzt"

    def __init__(
        self,
        config: LztConfig,
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
    # Category Listings
    # ---------------------------------------------------------------------------

    def get_listings(
        self,
        category: str,
        *,
        params: dict[str, Any] | None = None,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[LztListingPage]:
        """
        Fetch category listings from LZT Market.

        Generic endpoint — the app layer constructs category-specific
        query params (e.g. pmin, pmax, robux_min, game, etc.).

        Args:
            category: Category path segment (e.g. "steam", "roblox", "supercell").
            params: Query parameters forwarded to the API.
            auth_headers: Auth headers injected by the facade.
            proxy_url: Proxy URL injected by the facade.
        """
        url = self._build_url(LztEndpoints.category(category))

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
            page = LztListingPage.model_validate(body)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse listings response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response)
        return ApiResult.success(page, status_code=response.status_code, meta=meta)

    # ---------------------------------------------------------------------------
    # Item Details
    # ---------------------------------------------------------------------------

    def get_item(
        self,
        item_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """
        Get single item details by ID.

        Returns the raw response dict — item shapes vary by category.
        """
        url = self._build_url(LztEndpoints.item(item_id))

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
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse item response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response)
        return ApiResult.success(body, status_code=response.status_code, meta=meta)

    # ---------------------------------------------------------------------------
    # User Orders
    # ---------------------------------------------------------------------------

    def get_user_orders(
        self,
        *,
        params: dict[str, Any] | None = None,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[LztOrderPage]:
        """
        Fetch user orders / purchased accounts.

        Supports pagination and filter params (page, sort, order, login, etc.).
        """
        url = self._build_url(LztEndpoints.USER_ORDERS)

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
            page = LztOrderPage.model_validate(body)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse orders response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response)
        return ApiResult.success(page, status_code=response.status_code, meta=meta)

    # ---------------------------------------------------------------------------
    # Check Account (pre-purchase availability check)
    # ---------------------------------------------------------------------------

    def check_account(
        self,
        item_id: str,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[LztCheckAccountResult]:
        """
        Pre-purchase availability check.

        Verifies the item is still available and returns current pricing.
        This is a read-like/idempotent operation — no side effects.
        """
        url = self._build_url(LztEndpoints.check_account(item_id))

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
            result = LztCheckAccountResult.model_validate(body)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse check-account response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response)
        return ApiResult.success(result, status_code=response.status_code, meta=meta)

    # ---------------------------------------------------------------------------
    # Confirm Buy (purchase execution)
    # ---------------------------------------------------------------------------

    def confirm_buy(
        self,
        item_id: str,
        price: float,
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[LztPurchaseResult]:
        """
        Execute a purchase.

        Non-idempotent — deducts funds and transfers account ownership.
        The ``price`` must match the current LZT price (race-condition guard).
        """
        url = self._build_url(LztEndpoints.confirm_buy(item_id))

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=auth_headers,
                json_body={"price": price},
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=False,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
            result = LztPurchaseResult.model_validate(body)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse confirm-buy response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response)
        return ApiResult.success(result, status_code=response.status_code, meta=meta)

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    def _extract_meta(self, response: Any) -> dict[str, object]:
        """Extract metadata from response headers."""
        meta: dict[str, object] = {}
        if hasattr(response, "headers"):
            for key in ("X-Request-Id", "x-request-id"):
                value = response.headers.get(key)
                if value:
                    meta["request_id"] = value
                    break
        return meta

    def _handle_error(self, status_code: int, response: Any) -> ApiResult[Any]:
        """Map HTTP error codes to SDK error categories.

        LZT-specific: 403 responses are inspected for account-deleted
        indicators (the provider returns this when a listing was removed
        by the seller or administration).
        """
        # Try to parse body for error details
        message = f"HTTP {status_code}"
        details: dict[str, Any] = {}
        try:
            body = response.json() if hasattr(response, "json") else {}
            if isinstance(body, dict):
                errors = body.get("errors", [])
                if errors:
                    error_text = (
                        " ".join(errors) if isinstance(errors, list) else str(errors)
                    )
                    message = error_text or message
                    details["errors"] = errors

                    # LZT-specific: detect account-deleted via 403 body
                    if status_code == 403:
                        lower = error_text.lower()
                        if any(
                            phrase in lower
                            for phrase in (
                                "deleted by seller or administration",
                                "account is deleted",
                                "account is closed",
                            )
                        ):
                            return ApiResult.from_error(
                                ErrorCategory.NOT_FOUND,
                                "Account deleted by seller or administration",
                                status_code=status_code,
                                provider=self.PROVIDER,
                                is_retryable=False,
                                details=details,
                            )
        except Exception:
            pass

        category_map: dict[int, ErrorCategory] = {
            400: ErrorCategory.VALIDATION,
            401: ErrorCategory.AUTHENTICATION,
            403: ErrorCategory.AUTHENTICATION,
            404: ErrorCategory.NOT_FOUND,
            407: ErrorCategory.NETWORK,
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

        return ApiResult.from_error(
            category,
            message,
            status_code=status_code,
            provider=self.PROVIDER,
            retry_after=retry_after,
            is_retryable=is_retryable,
            details=details,
        )
