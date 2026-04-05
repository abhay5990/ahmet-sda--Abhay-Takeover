"""
Low-level R6Locker tracker client.

Handles raw HTTP communication with the R6Locker tracker.
Returns ApiResult with the raw account data dict on success.

The public tracker endpoint (/accounts/{id}) is unauthenticated
but requires browser-like headers and a matching referer to avoid
being blocked by Cloudflare protection.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.clients.trackers.r6locker.config import R6LockerConfig
from apis_sdk.clients.trackers.r6locker.endpoints import R6LockerEndpoints


class R6LockerClient:
    """
    Low-level R6Locker tracker client.

    Handles:
    - Request execution via injected transport
    - Response parsing
    - Error categorization from HTTP status codes

    Does NOT handle:
    - Proxy selection (caller provides proxy_url)
    - Retry logic (caller's responsibility)
    - Captcha solving or authenticated flows
    """

    PROVIDER = "r6locker"

    def __init__(
        self,
        config: R6LockerConfig,
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
    # Public tracker
    # ---------------------------------------------------------------------------

    def get_account_data(
        self,
        account_id: str,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """
        Fetch public account data from the R6Locker tracker.

        This is a read-only, unauthenticated endpoint.
        The referer header must match the expected profile URL pattern.
        """
        account_id = (account_id or "").strip()
        if not account_id:
            return ApiResult.from_error(
                ErrorCategory.VALIDATION,
                "account_id is required",
                provider=self.PROVIDER,
            )

        url = self._build_url(R6LockerEndpoints.account(account_id))

        # Referer must match the profile page pattern to pass Cloudflare
        headers = {
            "accept": "*/*",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "referer": f"{self._config.base_url}/profile/{account_id}",
        }

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=headers,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK,
                str(exc),
                provider=self.PROVIDER,
                is_retryable=True,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, response)

        try:
            body = response.json()
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse R6Locker response: {exc}",
                provider=self.PROVIDER,
            )

        return ApiResult.success(body, status_code=response.status_code)

    # ---------------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------------

    def _handle_error(self, status_code: int, response: Any) -> ApiResult[Any]:
        """Map HTTP error codes to SDK error categories."""
        category_map: dict[int, ErrorCategory] = {
            400: ErrorCategory.VALIDATION,
            403: ErrorCategory.AUTHENTICATION,
            404: ErrorCategory.NOT_FOUND,
            407: ErrorCategory.NETWORK,
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

        message = f"HTTP {status_code}"
        try:
            body = response.json() if hasattr(response, "json") else {}
            if isinstance(body, dict):
                message = str(body.get("message", body.get("error", message)))
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
