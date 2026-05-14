"""
Low-level Imgur API client.

Handles raw HTTP communication with the Imgur API v3.
Returns ApiResult with raw dicts.

Auth note:
    Imgur uses two auth patterns depending on the endpoint:
    - Upload/credits: ``Authorization: Client-ID {id}`` header
    - Album operations: ``client_id`` query parameter
    The facade manages this distinction; the client accepts
    whichever form the endpoint requires.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.clients.media.imgur.config import ImgurConfig
from apis_sdk.clients.media.imgur.endpoints import ImgurEndpoints


class ImgurClient:
    """
    Low-level Imgur API client.

    Handles:
    - Request execution via injected transport
    - Response parsing (raw JSON dicts)
    - Error categorization

    Does NOT handle:
    - Client-ID management or rotation (app-level)
    - Retry logic (deferred)
    - Proxy/User-Agent rotation (app-level)
    """

    PROVIDER = "imgur"

    def __init__(
        self,
        config: ImgurConfig,
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
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]:
        """Upload an image to Imgur.

        Args:
            image_data: Raw image bytes.
            file_name: Original file name (for Content-Disposition).
            auth_headers: Must include ``Authorization: Client-ID {id}``.
        """
        url = self._build_url(ImgurEndpoints.UPLOAD_IMAGE)
        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=auth_headers,
                files={"image": (file_name, image_data)},
                timeout=self._config.timeout,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )
        return self._handle_response(response)

    # ---------------------------------------------------------------------------
    # Album management (writes)
    # ---------------------------------------------------------------------------

    def create_album(
        self,
        *,
        client_id: str,
    ) -> ApiResult[dict[str, Any]]:
        """Create a new empty album.

        Imgur album creation uses ``client_id`` as a query parameter
        rather than the Authorization header.
        """
        url = self._build_url(ImgurEndpoints.ALBUM)
        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                params={"client_id": client_id},
                json_body={},
                timeout=self._config.timeout,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )
        return self._handle_response(response)

    def update_album(
        self,
        album_deletehash: str,
        *,
        deletehashes: list[str],
        cover_image_id: str | None = None,
        client_id: str,
    ) -> ApiResult[dict[str, Any]]:
        """Add images to an album.

        Uses ``client_id`` as a query parameter (same as create_album).

        Args:
            album_deletehash: The album's deletehash (NOT the album ID).
            deletehashes: Image deletehashes to add.
            cover_image_id: Optional image ID to use as cover.
            client_id: Imgur Client-ID for query param auth.
        """
        url = self._build_url(f"{ImgurEndpoints.ALBUM}/{album_deletehash}")
        payload: dict[str, Any] = {"deletehashes": deletehashes}
        if cover_image_id is not None:
            payload["cover"] = cover_image_id

        try:
            response = self._transport.request(
                HttpMethod.PUT,
                url,
                params={"client_id": client_id},
                json_body=payload,
                timeout=self._config.timeout,
            )
        except TransportError as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )
        return self._handle_response(response)

    # ---------------------------------------------------------------------------
    # Album fetch (read)
    # ---------------------------------------------------------------------------

    # Imgur's public v1 endpoint requires browser-like headers to avoid 429s.
    # Using the v3 API for album reads is aggressively rate-limited by Imgur.
    _BROWSER_HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/143.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "en,tr-TR;q=0.9,tr;q=0.8,en-US;q=0.7",
        "Origin": "https://imgur.com",
        "Referer": "https://imgur.com/",
        "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
    }

    def fetch_album_media(
        self,
        album_hash: str,
        *,
        client_id: str,
    ) -> ApiResult[list[dict]]:
        """Fetch media items from an Imgur album.

        Uses the public post/v1 endpoint with browser-like headers to avoid
        the aggressive rate limiting on the v3 API.

        Args:
            album_hash: The album hash (e.g. ``"abc123"`` from ``imgur.com/a/abc123``).
            client_id:  Imgur Client-ID for query param auth.

        Returns:
            ApiResult with a list of media item dicts on success.
            Each item contains at minimum: ``url``, ``ext``, ``type``.
        """
        url = f"{self._config.public_base_url}{ImgurEndpoints.ALBUM_FETCH.format(hash=album_hash)}"
        params = {"client_id": client_id, "include": "media,adconfig,account,tags"}
        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=self._BROWSER_HEADERS,
                params=params,
                timeout=self._config.timeout,
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
            media = body.get("media", [])
            return ApiResult.success(media, status_code=response.status_code)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Failed to parse album response: {exc}",
                provider=self.PROVIDER,
            )

    # ---------------------------------------------------------------------------
    # Credits (read)
    # ---------------------------------------------------------------------------

    def get_credits(
        self,
        *,
        auth_headers: dict[str, str],
    ) -> ApiResult[dict[str, Any]]:
        """Query remaining API credits for the current Client-ID."""
        url = self._build_url(ImgurEndpoints.CREDITS)
        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers=auth_headers,
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
                )
            # Imgur wraps successful responses in {"data": ..., "success": true, "status": 200}
            data = body.get("data", body) if isinstance(body, dict) else body
            return ApiResult.success(data, status_code=response.status_code)

        return self._handle_error(response.status_code, response)

    def _handle_error(self, status_code: int, response: Any) -> ApiResult[Any]:
        """Map HTTP error codes to SDK error categories."""
        message = f"HTTP {status_code}"
        details: dict[str, Any] = {}

        try:
            body = response.json() if hasattr(response, "json") else {}
            if isinstance(body, dict):
                # Imgur error format: {"data": {"error": "msg"}, "success": false}
                data = body.get("data", body)
                msg = (
                    data.get("error")
                    if isinstance(data, dict)
                    else body.get("error") or body.get("message")
                )
                if msg:
                    message = str(msg)
                    details["body"] = body
        except Exception:
            pass

        category_map: dict[int, ErrorCategory] = {
            400: ErrorCategory.VALIDATION,
            401: ErrorCategory.AUTHENTICATION,
            403: ErrorCategory.AUTHENTICATION,
            404: ErrorCategory.NOT_FOUND,
            422: ErrorCategory.VALIDATION,
            429: ErrorCategory.RATE_LIMIT,
            503: ErrorCategory.RATE_LIMIT,  # Imgur uses 503 for rate limiting
        }

        category = category_map.get(status_code, ErrorCategory.SERVER_ERROR)
        is_retryable = status_code >= 500 or status_code == 429

        retry_after: float | None = None
        if status_code in (429, 503):
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
