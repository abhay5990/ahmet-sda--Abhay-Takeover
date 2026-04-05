"""
Low-level StatsRoyale tracker client.

Handles raw HTTP communication with the StatsRoyale API.
Returns ApiResult with the raw profile data dict on success.

The API is hosted on Google Cloud Run and does not require
Cloudflare bypass — RequestsTransport is sufficient.
Browser-like headers (origin, referer) are still required.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.clients.trackers.statsroyale.config import StatsRoyaleConfig
from apis_sdk.clients.trackers.statsroyale.endpoints import StatsRoyaleEndpoints


class StatsRoyaleClient:
    """
    Low-level StatsRoyale tracker client.

    Handles:
    - Request execution via injected transport
    - Response parsing
    - Error categorization from HTTP status codes
    - StatsRoyale-specific success check (success: false responses)

    Does NOT handle:
    - Proxy selection (caller provides proxy_url)
    - Retry logic (caller's responsibility)
    - Arena mapping or data transformation (app-level)
    """

    PROVIDER = "statsroyale"

    def __init__(
        self,
        config: StatsRoyaleConfig,
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

    def get_profile(
        self,
        player_tag: str,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """
        Fetch player profile from StatsRoyale.

        Args:
            player_tag: CR player tag (e.g. 'QCR88LYGP', without '#').
            proxy_url: Optional proxy URL for the request.

        Returns:
            ApiResult with the raw profile data dict on success.
        """
        player_tag = (player_tag or "").strip().lstrip("#")
        if not player_tag:
            return ApiResult.from_error(
                ErrorCategory.VALIDATION,
                "player_tag is required",
                provider=self.PROVIDER,
            )

        url = self._build_url(StatsRoyaleEndpoints.profile(player_tag))

        # Origin and referer are required by the API
        headers = self._config.get_default_headers()

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
                f"Failed to parse StatsRoyale response: {exc}",
                provider=self.PROVIDER,
            )

        # StatsRoyale returns {"success": false, ...} for some failures
        if isinstance(body, dict) and body.get("success") is False:
            message = str(body.get("message", body.get("error", "API returned success=false")))
            return ApiResult.from_error(
                ErrorCategory.NOT_FOUND,
                message,
                status_code=response.status_code,
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
