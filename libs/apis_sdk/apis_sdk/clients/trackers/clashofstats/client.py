"""
Low-level ClashOfStats tracker client.

Handles raw HTTP communication with the ClashOfStats API.
Returns ApiResult with the raw player data dict on success.

ClashOfStats is Cloudflare-protected, so CurlCffiTransport with
browser impersonation is required for reliable access.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.clients.trackers.clashofstats.config import ClashOfStatsConfig
from apis_sdk.clients.trackers.clashofstats.endpoints import ClashOfStatsEndpoints


class ClashOfStatsClient:
    """
    Low-level ClashOfStats tracker client.

    Handles:
    - Request execution via injected transport
    - Response parsing
    - Error categorization from HTTP status codes
    - Cloudflare challenge detection (403 with cloudflare body)

    Does NOT handle:
    - Proxy selection (caller provides proxy_url)
    - Retry logic (caller's responsibility)
    - Race condition / parallel fetch strategy (app-level)
    """

    PROVIDER = "clashofstats"

    def __init__(
        self,
        config: ClashOfStatsConfig,
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

    def get_player_data(
        self,
        player_tag: str,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """
        Fetch player data from ClashOfStats.

        Args:
            player_tag: CoC player tag (e.g. 'QCR88LYGP', without '#').
            proxy_url: Optional proxy URL for the request.

        Returns:
            ApiResult with the raw player data dict on success.
        """
        player_tag = (player_tag or "").strip().lstrip("#")
        if not player_tag:
            return ApiResult.from_error(
                ErrorCategory.VALIDATION,
                "player_tag is required",
                provider=self.PROVIDER,
            )

        url = self._build_url(ClashOfStatsEndpoints.player(player_tag))

        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
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

        # Cloudflare challenge detection — 200 but HTML instead of JSON
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return ApiResult.from_error(
                ErrorCategory.NETWORK,
                "Cloudflare challenge or unexpected content type",
                status_code=response.status_code,
                provider=self.PROVIDER,
                is_retryable=True,
            )

        try:
            body = response.json()
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse ClashOfStats response: {exc}",
                provider=self.PROVIDER,
            )

        return ApiResult.success(body, status_code=response.status_code)

    # ---------------------------------------------------------------------------
    # Error handling
    # ---------------------------------------------------------------------------

    def _handle_error(self, status_code: int, response: Any) -> ApiResult[Any]:
        """Map HTTP error codes to SDK error categories."""
        # Cloudflare 403 detection
        if status_code == 403:
            try:
                text = response.text if hasattr(response, "text") else ""
                if "cloudflare" in text.lower():
                    return ApiResult.from_error(
                        ErrorCategory.NETWORK,
                        "Cloudflare challenge detected",
                        status_code=status_code,
                        provider=self.PROVIDER,
                        is_retryable=True,
                    )
            except Exception:
                pass

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
