"""
Low-level Dropbox API client.

Handles raw HTTP communication with the Dropbox API v2.
Returns ApiResult with raw dicts.

Auth note:
    Dropbox uses ``Authorization: Bearer {token}`` headers.
    The token is passed via ``auth_headers`` from the facade.

Upload note:
    The file-upload endpoint uses ``application/octet-stream`` body
    with metadata in a ``Dropbox-API-Arg`` JSON header — NOT multipart.
"""

from __future__ import annotations

import json
from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.clients.media.dropbox.config import DropboxConfig
from apis_sdk.clients.media.dropbox.endpoints import DropboxEndpoints


class DropboxClient:
    """
    Low-level Dropbox API client.

    Handles:
    - File upload via content endpoint (octet-stream)
    - Shared link creation via RPC endpoint
    - Response parsing (raw JSON dicts)
    - Error categorization

    Does NOT handle:
    - Access token management / OAuth2 refresh (app-level)
    - Folder structure / naming conventions (app-level)
    - Batch upload orchestration (app-level)
    - Retry logic (deferred)
    """

    PROVIDER = "dropbox"

    def __init__(
        self,
        config: DropboxConfig,
        transport: BaseHttpTransport,
        *,
        logger: SdkLogger | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._logger = logger or NullLogger()

    # ---------------------------------------------------------------------------
    # Upload (write) — content endpoint
    # ---------------------------------------------------------------------------

    def upload_file(
        self,
        *,
        file_data: bytes,
        dest_path: str,
        auth_headers: dict[str, str],
        mode: str = "add",
        autorename: bool = True,
        mute: bool = True,
    ) -> ApiResult[dict[str, Any]]:
        """Upload a file to Dropbox.

        Uses the content upload endpoint with octet-stream body and
        ``Dropbox-API-Arg`` header for metadata.

        Args:
            file_data: Raw file bytes.
            dest_path: Destination path in Dropbox (e.g. ``/media/img.png``).
            auth_headers: Must include ``Authorization: Bearer {token}``.
            mode: Write mode (``add``, ``overwrite``, ``update``).
            autorename: Auto-rename on conflict.
            mute: Suppress desktop notifications.
        """
        url = f"{self._config.content_base_url}{DropboxEndpoints.UPLOAD}"

        api_arg = json.dumps({
            "path": dest_path,
            "mode": mode,
            "autorename": autorename,
            "mute": mute,
        })

        headers = {
            **auth_headers,
            "Content-Type": "application/octet-stream",
            "Dropbox-API-Arg": api_arg,
        }

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=headers,
                data=file_data,
                timeout=self._config.timeout,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )
        return self._handle_response(response)

    # ---------------------------------------------------------------------------
    # Shared link (write) — RPC endpoint
    # ---------------------------------------------------------------------------

    def create_shared_link(
        self,
        *,
        path: str,
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]:
        """Create a shared link for a file.

        If a shared link already exists for the path, Dropbox returns 409
        ``shared_link_already_exists``. Inline metadata MAY be included, but
        is omitted when custom settings (as we send) could be incompatible
        with the existing link — in that case the facade falls back to
        ``list_shared_links``.

        Args:
            path: File path in Dropbox (e.g. ``/media/img.png``).
            auth_headers: Must include ``Authorization: Bearer {token}``.
        """
        url = f"{self._config.api_base_url}{DropboxEndpoints.CREATE_SHARED_LINK}"

        headers = {**auth_headers, "Content-Type": "application/json"}

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=headers,
                json_body={
                    "path": path,
                    "settings": {
                        "requested_visibility": "public",
                        "audience": "public",
                        "access": "viewer",
                    },
                },
                timeout=self._config.timeout,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )
        return self._handle_shared_link_response(response)

    def list_shared_links(
        self,
        *,
        path: str,
        auth_headers: dict[str, str],
        direct_only: bool = True,
        cursor: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """List shared links for a path.

        Used as the recommended fallback when ``create_shared_link`` returns
        409 ``shared_link_already_exists`` without metadata (per Dropbox spec,
        metadata is omitted when the request specifies custom settings that
        may be incompatible with the existing link).

        Args:
            path: File path in Dropbox.
            auth_headers: Must include ``Authorization: Bearer {token}``.
            direct_only: If True, suppress links to parent folders.
            cursor: Pagination cursor from a previous call.
        """
        url = f"{self._config.api_base_url}{DropboxEndpoints.LIST_SHARED_LINKS}"

        headers = {**auth_headers, "Content-Type": "application/json"}

        body: dict[str, Any] = {"path": path, "direct_only": direct_only}
        if cursor:
            body["cursor"] = cursor

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=headers,
                json_body=body,
                timeout=self._config.timeout,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )
        return self._handle_response(response)

    # ---------------------------------------------------------------------------
    # Metadata (read) — RPC endpoint
    # ---------------------------------------------------------------------------

    def get_metadata(
        self,
        *,
        path: str,
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]:
        """Get file/folder metadata.

        Args:
            path: File or folder path in Dropbox.
            auth_headers: Must include ``Authorization: Bearer {token}``.
        """
        url = f"{self._config.api_base_url}{DropboxEndpoints.GET_METADATA}"

        headers = {**auth_headers, "Content-Type": "application/json"}

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=headers,
                json_body={"path": path},
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
        if response.is_success:
            try:
                body = response.json()
            except Exception as exc:
                return ApiResult.from_error(
                    ErrorCategory.UNKNOWN,
                    f"Failed to parse response: {exc}",
                    provider=self.PROVIDER,
                    status_code=response.status_code,
                )
            return ApiResult.success(body, status_code=response.status_code)

        return self._handle_error(response.status_code, response)

    def _handle_shared_link_response(
        self, response: Any,
    ) -> ApiResult[dict[str, Any]]:
        """Handle shared link response, including 409 (link already exists).

        Dropbox returns 409 when a shared link already exists. Per the API
        spec, ``error.shared_link_already_exists.metadata`` MAY be omitted
        when the request specifies custom settings that could be incompatible
        with the existing link — which is our case (we pass ``requested_visibility``
        / ``audience`` / ``access``). In that case the caller (facade) must
        fall back to ``list_shared_links``.
        """
        if response.is_success:
            try:
                body = response.json()
            except Exception as exc:
                return ApiResult.from_error(
                    ErrorCategory.UNKNOWN,
                    f"Failed to parse response: {exc}",
                    provider=self.PROVIDER,
                    status_code=response.status_code,
                )
            return ApiResult.success(body, status_code=response.status_code)

        # 409 = shared_link_already_exists — try to extract inline metadata
        if response.status_code == 409:
            try:
                body = response.json()
                existing = (
                    body.get("error", {})
                    .get("shared_link_already_exists", {})
                    .get("metadata", {})
                )
                if existing:
                    return ApiResult.success(
                        existing, status_code=response.status_code,
                    )
                self._logger.debug(
                    f"Dropbox 409 shared_link_already_exists without metadata; body={body!r}",
                )
            except Exception:
                pass

        return self._handle_error(response.status_code, response)

    def _handle_error(
        self, status_code: int, response: Any,
    ) -> ApiResult[Any]:
        """Map HTTP error codes to SDK error categories."""
        message = f"HTTP {status_code}"
        details: dict[str, Any] = {}

        try:
            body = response.json() if hasattr(response, "json") else {}
            if isinstance(body, dict):
                err_summary = body.get("error_summary", "")
                user_message = body.get("user_message", {})
                if isinstance(user_message, dict):
                    msg = user_message.get("text", "")
                else:
                    msg = str(user_message)

                if err_summary:
                    message = err_summary
                elif msg:
                    message = msg
                details["body"] = body
        except Exception:
            pass

        category_map: dict[int, ErrorCategory] = {
            400: ErrorCategory.VALIDATION,
            401: ErrorCategory.AUTHENTICATION,
            403: ErrorCategory.AUTHENTICATION,
            404: ErrorCategory.NOT_FOUND,
            409: ErrorCategory.CONFLICT,
            429: ErrorCategory.RATE_LIMIT,
        }

        category = category_map.get(status_code, ErrorCategory.SERVER_ERROR)
        is_retryable = status_code >= 500 or status_code == 429

        retry_after: float | None = None
        if status_code == 429:
            try:
                retry_after = float(
                    response.headers.get("Retry-After", 5),
                )
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
