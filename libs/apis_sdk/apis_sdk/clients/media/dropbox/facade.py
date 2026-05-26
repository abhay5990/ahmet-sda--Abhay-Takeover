"""
Dropbox high-level facade.

Provides a clean consumer-facing API that coordinates:
- Bearer token injection into all requests
- Upload + shared-link creation as a single operation
- Error boundary (client exceptions -> ApiResult)

This facade is intentionally thin.  Dropbox is used as a media
hosting service with no retry or proxy requirements at the SDK level.

Deferred responsibilities (remain outside the SDK):
- OAuth2 token refresh / rotation
- Folder structure / naming conventions
- Batch upload orchestration
"""

from __future__ import annotations

from typing import Any, Protocol

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.result import ApiResult


class DropboxApiClient(Protocol):
    """Protocol for the low-level Dropbox client."""

    def upload_file(
        self,
        *,
        file_data: bytes,
        dest_path: str,
        auth_headers: dict[str, str],
        mode: str = "add",
        autorename: bool = True,
        mute: bool = True,
    ) -> ApiResult[dict[str, Any]]: ...

    def create_shared_link(
        self,
        *,
        path: str,
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]: ...

    def list_shared_links(
        self,
        *,
        path: str,
        auth_headers: dict[str, str],
        direct_only: bool = True,
        cursor: str | None = None,
    ) -> ApiResult[dict[str, Any]]: ...

    def get_metadata(
        self,
        *,
        path: str,
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]: ...


class DropboxFacade:
    """
    High-level Dropbox interface.

    Coordinates Bearer token injection around the low-level DropboxClient.
    All methods return ApiResult -- no exceptions escape.
    """

    def __init__(
        self,
        client: DropboxApiClient,
        access_token: str,
    ) -> None:
        self._client = client
        self._access_token = access_token

    @property
    def access_token(self) -> str:
        return self._access_token

    def set_access_token(self, access_token: str) -> None:
        """Update the access token (e.g. after OAuth2 refresh)."""
        self._access_token = access_token

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

    # ---------------------------------------------------------------------------
    # Upload (write)
    # ---------------------------------------------------------------------------

    def upload_file(
        self,
        file_data: bytes,
        dest_path: str,
        *,
        mode: str = "add",
        autorename: bool = True,
    ) -> ApiResult[dict[str, Any]]:
        """Upload a file to Dropbox.

        Args:
            file_data: Raw file bytes.
            dest_path: Destination path (e.g. ``/media/img.png``).
            mode: Write mode (``add``, ``overwrite``).
            autorename: Auto-rename on conflict.
        """
        try:
            return self._client.upload_file(
                file_data=file_data,
                dest_path=dest_path,
                auth_headers=self._auth_headers(),
                mode=mode,
                autorename=autorename,
            )
        except Exception as exc:
            return self._error(exc)

    # ---------------------------------------------------------------------------
    # Shared link (write)
    # ---------------------------------------------------------------------------

    def create_shared_link(
        self,
        path: str,
    ) -> ApiResult[dict[str, Any]]:
        """Create a public shared link for a file.

        If a link already exists, returns the existing link metadata. When
        Dropbox returns 409 ``shared_link_already_exists`` without inline
        metadata (the API omits it when custom settings could be incompatible
        with the existing link), this falls back to ``list_shared_links`` to
        retrieve the existing link URL.

        Args:
            path: File path in Dropbox (e.g. ``/media/img.png``).

        Returns:
            ApiResult containing link metadata with ``url`` field.
        """
        try:
            result = self._client.create_shared_link(
                path=path,
                auth_headers=self._auth_headers(),
            )
        except Exception as exc:
            return self._error(exc)

        if result.ok or result.status_code != 409:
            return result

        try:
            list_result = self._client.list_shared_links(
                path=path,
                auth_headers=self._auth_headers(),
                direct_only=True,
            )
        except Exception as exc:
            return self._error(exc)

        if not list_result.ok:
            return result

        links = (list_result.data or {}).get("links") or []
        if not links:
            return result

        return ApiResult.success(links[0], status_code=200)

    # ---------------------------------------------------------------------------
    # Upload + share (convenience)
    # ---------------------------------------------------------------------------

    def upload_and_share(
        self,
        file_data: bytes,
        dest_path: str,
        *,
        mode: str = "add",
        autorename: bool = True,
    ) -> ApiResult[dict[str, Any]]:
        """Upload a file and create a public shared link in one call.

        Combines ``upload_file`` + ``create_shared_link``.
        On success, returns the shared link metadata (includes ``url``).

        Args:
            file_data: Raw file bytes.
            dest_path: Destination path in Dropbox.
            mode: Write mode.
            autorename: Auto-rename on conflict.
        """
        upload_result = self.upload_file(
            file_data, dest_path, mode=mode, autorename=autorename,
        )
        if not upload_result.ok:
            return upload_result

        uploaded_path = upload_result.data.get(
            "path_display", dest_path,
        )
        return self.create_shared_link(uploaded_path)

    # ---------------------------------------------------------------------------
    # Metadata (read)
    # ---------------------------------------------------------------------------

    def get_metadata(
        self,
        path: str,
    ) -> ApiResult[dict[str, Any]]:
        """Get file or folder metadata.

        Args:
            path: File or folder path in Dropbox.
        """
        try:
            return self._client.get_metadata(
                path=path,
                auth_headers=self._auth_headers(),
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
            f"Unexpected Dropbox facade error: {exc}",
            provider="dropbox",
            is_retryable=False,
        )
