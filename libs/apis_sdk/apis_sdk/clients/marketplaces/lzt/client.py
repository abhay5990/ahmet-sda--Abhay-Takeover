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
    LztBatchJob,
    LztBatchResult,
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
    # User Items (own listings)
    # ---------------------------------------------------------------------------

    def get_user_items(
        self,
        *,
        params: dict[str, Any] | None = None,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[LztOrderPage]:
        """Fetch user's own items/listings (e.g. closed/sold accounts)."""
        url = self._build_url(LztEndpoints.USER_ITEMS)

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
                f"Failed to parse user items response: {exc}",
                provider=self.PROVIDER,
            )

        meta = self._extract_meta(response)
        return ApiResult.success(page, status_code=response.status_code, meta=meta)

    # ---------------------------------------------------------------------------
    # Mail Access (email:password validation + inbox)
    # ---------------------------------------------------------------------------

    def get_email_letters(
        self,
        *,
        email_password: str,
        limit: int = 50,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """
        Fetch inbox letters for ``email:password`` via the LZT Mail Access API.

        Single-call semantics: if letters are returned, the password is valid.
        A 403 response indicates invalid credentials (wrong password / locked).
        A 401 indicates the API token itself is unauthorized.

        Body-level ``retry_request`` responses are mapped to a retryable
        SERVER_ERROR so the facade retry policy transparently re-issues the call.

        Args:
            email_password: ``email:password`` string passed verbatim to LZT.
            limit: Number of letters to fetch (LZT clamps to 10..50).
            auth_headers: Bearer headers injected by the facade.
            proxy_url: Proxy URL injected by the facade.
        """
        url = self._build_url(LztEndpoints.LETTERS2)
        params: dict[str, Any] = {
            "email_password": email_password,
            "limit": max(10, min(50, int(limit))),
        }

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

        try:
            body = response.json() if hasattr(response, "json") else {}
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}

        # Body-level 'retry_request' — re-issue via retry policy
        errors = body.get("errors") or []
        error_text = (
            " ".join(errors) if isinstance(errors, list) else str(errors)
        ).strip()
        if error_text and "retry_request" in error_text.lower():
            return ApiResult.from_error(
                ErrorCategory.SERVER_ERROR,
                "retry_request",
                status_code=response.status_code,
                provider=self.PROVIDER,
                is_retryable=True,
                details={"errors": errors},
            )

        if response.is_success and body.get("letters") is not None:
            meta = self._extract_meta(response)
            return ApiResult.success(body, status_code=response.status_code, meta=meta)

        if not response.is_success:
            # LZT returns rate-limit as 403 with "must wait N seconds" body.
            # Detect and remap to RATE_LIMIT so facade retry policy handles it.
            import re
            if error_text:
                wait_match = re.search(r"wait at least (\d+) seconds", error_text)
                if wait_match:
                    retry_after = float(wait_match.group(1)) + 1
                    return ApiResult.from_error(
                        ErrorCategory.RATE_LIMIT,
                        error_text,
                        status_code=response.status_code,
                        provider=self.PROVIDER,
                        retry_after=retry_after,
                        is_retryable=True,
                        details={"errors": errors},
                    )
            return self._handle_error(response.status_code, response)

        # 2xx but no letters field — treat as unknown success shape
        return ApiResult.from_error(
            ErrorCategory.UNKNOWN,
            error_text or "Unexpected response shape (no 'letters' field)",
            status_code=response.status_code,
            provider=self.PROVIDER,
            details={"body_keys": list(body.keys())},
        )

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
    # Batch
    # ---------------------------------------------------------------------------

    def batch(
        self,
        jobs: list[LztBatchJob],
        *,
        auth_headers: dict[str, str],
        proxy_url: str | None = None,
    ) -> ApiResult[LztBatchResult]:
        """
        Execute multiple API requests in a single call.

        Maximum 10 jobs per batch. Following methods are unavailable:
        - GET /{item_id}/image
        - /item/fast-sell

        Args:
            jobs: List of batch jobs (max 10).
            auth_headers: Auth headers injected by the facade.
            proxy_url: Proxy URL injected by the facade.
        """
        if len(jobs) > 10:
            return ApiResult.from_error(
                ErrorCategory.VALIDATION,
                "Maximum 10 batch jobs allowed",
                provider=self.PROVIDER,
            )

        url = self._build_url(LztEndpoints.BATCH)
        payload = [
            {k: v for k, v in job.model_dump().items() if v is not None}
            for job in jobs
        ]

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
            result = LztBatchResult.model_validate(body)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse batch response: {exc}",
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

                    # LZT-specific: detect maintenance mode (503)
                    # LZT returns: "Технические работы // Technical works."
                    _lower = error_text.lower()
                    if "technical works" in _lower or "технические работы" in _lower:
                        details["maintenance"] = True
                        return ApiResult.from_error(
                            ErrorCategory.SERVER_ERROR,
                            message,
                            status_code=status_code,
                            provider=self.PROVIDER,
                            is_retryable=True,
                            details=details,
                        )

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
