"""
ImageShack high-level facade.

Provides a clean consumer-facing API that coordinates:
- API key injection into upload requests
- Error boundary (client exceptions -> ApiResult)

This facade is intentionally thin.  ImageShack has a single
upload endpoint with no retry or proxy requirements at the SDK level.

Deferred responsibilities (remain outside the SDK):
- API key management / config reload
- Album name generation
- Batch upload orchestration
"""

from __future__ import annotations

from typing import Any, Protocol

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.result import ApiResult


class ImageShackApiClient(Protocol):
    """Protocol for the low-level ImageShack client."""

    def upload_image(
        self,
        *,
        image_data: bytes,
        file_name: str,
        content_type: str,
        api_key: str,
        album: str | None = None,
        public: bool = False,
    ) -> ApiResult[dict[str, Any]]: ...


class ImageShackFacade:
    """
    High-level ImageShack interface.

    Coordinates API key injection around the low-level ImageShackClient.
    All methods return ApiResult -- no exceptions escape.

    Note: No BaseAuthProvider is used because ImageShack sends the
    API key as a multipart form field, not as an HTTP header.
    """

    def __init__(
        self,
        client: ImageShackApiClient,
        api_key: str,
    ) -> None:
        self._client = client
        self._api_key = api_key

    @property
    def api_key(self) -> str:
        return self._api_key

    def set_api_key(self, api_key: str) -> None:
        """Update the API key (e.g. after external config reload)."""
        self._api_key = api_key

    # ---------------------------------------------------------------------------
    # Upload (write)
    # ---------------------------------------------------------------------------

    def upload_image(
        self,
        image_data: bytes,
        file_name: str,
        content_type: str,
        *,
        album: str | None = None,
        public: bool = False,
    ) -> ApiResult[dict[str, Any]]:
        """Upload an image to ImageShack.

        Args:
            image_data: Raw image bytes.
            file_name: Original file name.
            content_type: MIME type (e.g. ``image/png``).
            album: Optional album title.
            public: Whether the image is publicly listed.
        """
        try:
            return self._client.upload_image(
                image_data=image_data,
                file_name=file_name,
                content_type=content_type,
                api_key=self._api_key,
                album=album,
                public=public,
            )
        except Exception as exc:
            return self._error(exc)

    # ---------------------------------------------------------------------------
    # Internal
    # ---------------------------------------------------------------------------

    @staticmethod
    def _error(exc: Exception) -> ApiResult[Any]:
        return ApiResult.from_error(
            ErrorCategory.UNKNOWN,
            f"Unexpected ImageShack facade error: {exc}",
            provider="imageshack",
            is_retryable=False,
        )
