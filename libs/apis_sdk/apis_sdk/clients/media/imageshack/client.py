"""
Low-level ImageShack API client.

Handles raw HTTP communication with the ImageShack API v2.
Returns ApiResult with raw dicts.

Auth note:
    ImageShack authenticates via an ``api_key`` field in the
    multipart form data, not via HTTP headers.  This means
    BaseAuthProvider is not applicable here.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.clients.media.imageshack.config import ImageShackConfig


class ImageShackClient:
    """
    Low-level ImageShack API client.

    Handles:
    - Request execution via injected transport
    - Response parsing (raw JSON dicts)
    - Error categorization

    Does NOT handle:
    - API key management / config reload (app-level)
    - Album name generation (app-level)
    - Batch upload orchestration (app-level)
    - Retry logic (deferred)
    """

    PROVIDER = "imageshack"
    UPLOAD_PATH = "/images"

    def __init__(
        self,
        config: ImageShackConfig,
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
    # Upload (write)
    # ---------------------------------------------------------------------------

    def upload_image(
        self,
        *,
        image_data: bytes,
        file_name: str,
        content_type: str,
        api_key: str,
        album: str | None = None,
        public: bool = False,
    ) -> ApiResult[dict[str, Any]]:
        """Upload an image to ImageShack.

        Args:
            image_data: Raw image bytes.
            file_name: Original file name.
            content_type: MIME type (e.g. ``image/png``).
            api_key: ImageShack API key (sent as form field).
            album: Optional album title to assign the image to.
            public: Whether the image should be publicly listed.
        """
        url = self._build_url(self.UPLOAD_PATH)

        form_data: dict[str, str] = {
            "api_key": api_key,
            "public": str(public).lower(),
        }
        if album:
            form_data["album"] = album

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                data=form_data,
                files={"file": (file_name, image_data, content_type)},
                timeout=self._config.timeout,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )
        return self._handle_response(response)

    # ---------------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------------

    def _handle_response(self, response: Any) -> ApiResult[dict[str, Any]]:
        """Parse a transport response into ApiResult."""
        try:
            body = response.json()
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse response: {exc}",
                provider=self.PROVIDER,
                status_code=response.status_code,
            )

        if not response.is_success:
            return self._handle_error(response.status_code, body)

        # ImageShack wraps responses in {"success": true, "result": {...}}
        if isinstance(body, dict) and not body.get("success", True):
            return self._handle_error(response.status_code, body)

        # Extract the image data from result.images[0] if present
        result_data = body
        if isinstance(body, dict) and "result" in body:
            result_data = body["result"]

        return ApiResult.success(result_data, status_code=response.status_code)

    def _handle_error(
        self, status_code: int, body: Any,
    ) -> ApiResult[Any]:
        """Map HTTP error codes to SDK error categories."""
        message = f"HTTP {status_code}"
        details: dict[str, Any] = {}

        if isinstance(body, dict):
            error_msg = body.get("error", {})
            if isinstance(error_msg, dict):
                message = error_msg.get("message", message)
            elif isinstance(error_msg, str) and error_msg:
                message = error_msg
            details["body"] = body

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

        return ApiResult.from_error(
            category,
            message,
            status_code=status_code,
            provider=self.PROVIDER,
            is_retryable=is_retryable,
            details=details,
        )
