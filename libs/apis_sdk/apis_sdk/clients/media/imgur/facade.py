"""
Imgur high-level facade.

Provides a clean consumer-facing API that coordinates:
- Client-ID injection (header or query param, per endpoint)
- Error boundary (client exceptions -> ApiResult)

This facade is intentionally thin.  Imgur is a simple media API
with no retry or proxy requirements at the SDK level.

Deferred responsibilities (remain outside the SDK):
- Multi-client-ID rotation / failover
- Proxy and User-Agent rotation
- Batch upload orchestration
- Album workflow logic
"""

from __future__ import annotations

from typing import Any, Protocol

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.result import ApiResult


class ImgurApiClient(Protocol):
    """Protocol for the low-level Imgur client."""

    def upload_image(
        self,
        *,
        image_data: bytes,
        file_name: str,
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]: ...

    def create_album(
        self,
        *,
        client_id: str,
    ) -> ApiResult[dict[str, Any]]: ...

    def update_album(
        self,
        album_deletehash: str,
        *,
        deletehashes: list[str],
        cover_image_id: str | None = None,
        client_id: str,
    ) -> ApiResult[dict[str, Any]]: ...

    def fetch_album_media(
        self,
        album_hash: str,
        *,
        client_id: str,
    ) -> ApiResult[list[dict]]: ...

    def get_credits(
        self,
        *,
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]: ...


class ImgurFacade:
    """
    High-level Imgur interface.

    Coordinates Client-ID injection around the low-level ImgurClient.
    All methods return ApiResult -- no exceptions escape.

    Note: No BaseAuthProvider is used because Imgur's auth model
    has two patterns (header for uploads/credits, query param for
    album operations) which don't map cleanly to a single provider.
    """

    def __init__(
        self,
        client: ImgurApiClient,
        client_id: str,
    ) -> None:
        self._client = client
        self._client_id = client_id

    @property
    def client_id(self) -> str:
        return self._client_id

    def set_client_id(self, client_id: str) -> None:
        """Update the Client-ID (e.g. after external rotation)."""
        self._client_id = client_id

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Client-ID {self._client_id}"}

    # ---------------------------------------------------------------------------
    # Upload (write)
    # ---------------------------------------------------------------------------

    def upload_image(
        self,
        image_data: bytes,
        file_name: str,
    ) -> ApiResult[dict[str, Any]]:
        """Upload an image to Imgur."""
        try:
            return self._client.upload_image(
                image_data=image_data,
                file_name=file_name,
                auth_headers=self._auth_headers(),
            )
        except Exception as exc:
            return self._error(exc)

    # ---------------------------------------------------------------------------
    # Album management (writes)
    # ---------------------------------------------------------------------------

    def create_album(self) -> ApiResult[dict[str, Any]]:
        """Create a new empty album."""
        try:
            return self._client.create_album(client_id=self._client_id)
        except Exception as exc:
            return self._error(exc)

    def update_album(
        self,
        album_deletehash: str,
        *,
        deletehashes: list[str],
        cover_image_id: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Add images to an album."""
        try:
            return self._client.update_album(
                album_deletehash,
                deletehashes=deletehashes,
                cover_image_id=cover_image_id,
                client_id=self._client_id,
            )
        except Exception as exc:
            return self._error(exc)

    # ---------------------------------------------------------------------------
    # Album fetch (read)
    # ---------------------------------------------------------------------------

    def fetch_album_media(self, album_hash: str) -> ApiResult[list[dict]]:
        """Fetch media items from an Imgur album by hash.

        Args:
            album_hash: The album hash (e.g. ``"abc123"`` from ``imgur.com/a/abc123``).

        Returns:
            ApiResult with a list of media item dicts (url, ext, type, ...).
        """
        try:
            return self._client.fetch_album_media(
                album_hash,
                client_id=self._client_id,
            )
        except Exception as exc:
            return self._error(exc)

    # ---------------------------------------------------------------------------
    # Credits (read)
    # ---------------------------------------------------------------------------

    def get_credits(self) -> ApiResult[dict[str, Any]]:
        """Query remaining API credits for the current Client-ID."""
        try:
            return self._client.get_credits(auth_headers=self._auth_headers())
        except Exception as exc:
            return self._error(exc)

    # ---------------------------------------------------------------------------
    # Internal
    # ---------------------------------------------------------------------------

    @staticmethod
    def _error(exc: Exception) -> ApiResult[Any]:
        return ApiResult.from_error(
            ErrorCategory.UNKNOWN,
            f"Unexpected Imgur facade error: {exc}",
            provider="imgur",
            is_retryable=False,
        )
