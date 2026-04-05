"""
HTTP transport implementation using the `curl_cffi` library.

Provides TLS fingerprint impersonation (browser identity spoofing)
for providers behind anti-bot protection (e.g., Cloudflare).

This is NOT the default transport. Use only for scraping-domain
providers that require browser impersonation to function.

ADR: docs/adr/0002-curl-cffi-transport.md
"""

from __future__ import annotations

from typing import Any

from curl_cffi import requests as cffi_requests
from curl_cffi.requests.exceptions import (
    ConnectionError as CffiConnectionError,
    ProxyError as CffiProxyError,
    RequestException as CffiRequestException,
    Timeout as CffiTimeout,
)

from apis_sdk.core.enums import HttpMethod
from apis_sdk.core.exceptions import TimeoutError, TransportError
from apis_sdk.infrastructure.http.base import BaseHttpTransport, TransportResponse


class CurlCffiTransport(BaseHttpTransport):
    """
    Transport implementation backed by curl_cffi.

    Uses curl_cffi's browser impersonation to produce TLS fingerprints
    indistinguishable from real browsers, bypassing anti-bot detection.

    Args:
        impersonate: Browser identity to impersonate (e.g., "chrome124").
            Set per-transport-instance, not per-request, because changing
            fingerprint mid-session is suspicious to anti-bot systems.
        default_timeout: Default request timeout in seconds.
        default_headers: Headers merged into every request.
        verify_ssl: Whether to verify TLS certificates.
    """

    def __init__(
        self,
        *,
        impersonate: str = "chrome124",
        default_timeout: float = 30.0,
        default_headers: dict[str, str] | None = None,
        verify_ssl: bool = True,
    ) -> None:
        super().__init__(
            default_timeout=default_timeout,
            default_headers=default_headers,
            verify_ssl=verify_ssl,
        )
        self._impersonate = impersonate
        self._session = self._create_session()

    def _create_session(self) -> cffi_requests.Session:
        """Create a configured curl_cffi session."""
        return cffi_requests.Session(
            impersonate=self._impersonate,
            verify=self._verify_ssl,
        )

    def _send(
        self,
        method: HttpMethod,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None,
        json_body: dict[str, Any] | None,
        data: Any | None,
        files: dict[str, Any] | None,
        timeout: float,
        proxy_url: str | None,
    ) -> TransportResponse:
        kwargs: dict[str, Any] = {
            "method": method.value,
            "url": url,
            "headers": headers,
            "params": params,
            "json": json_body,
            "data": data,
            "files": files,
            "timeout": timeout,
        }

        if proxy_url:
            kwargs["proxy"] = proxy_url

        try:
            response = self._session.request(**kwargs)
        except CffiTimeout as exc:
            raise TimeoutError(
                f"Request to {url} timed out after {timeout}s",
                timeout_seconds=timeout,
            ) from exc
        except CffiProxyError as exc:
            raise TransportError(
                f"Proxy error for {url}: {exc}",
                details={"proxy_url": proxy_url or ""},
            ) from exc
        except CffiConnectionError as exc:
            raise TransportError(
                f"Connection error for {url}: {exc}",
            ) from exc
        except CffiRequestException as exc:
            raise TransportError(
                f"Request failed for {url}: {exc}",
            ) from exc

        return TransportResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=response.content,
        )

    def reset_session(self) -> None:
        """Close the current session and create a fresh one."""
        self._session.close()
        self._session = self._create_session()

    def close(self) -> None:
        """Close the underlying curl_cffi session."""
        self._session.close()
