"""
HTTP transport implementation using the `requests` library.

This is the default transport shipped with the SDK.
"""

from __future__ import annotations

from typing import Any

import requests

from apis_sdk.core.enums import HttpMethod
from apis_sdk.core.exceptions import TimeoutError, TransportError
from apis_sdk.infrastructure.http.base import BaseHttpTransport, TransportResponse
from apis_sdk.infrastructure.http.session_factory import SessionFactory


class RequestsTransport(BaseHttpTransport):
    """
    Transport implementation backed by requests.Session.

    Features:
    - Connection pooling via Session
    - Configurable retry at the urllib3 level
    - SSL verification control
    - Proxy support per-request

    Lifecycle / ownership:
        Transport instances are intended to be long-lived and reused across
        many facade calls. The session is created at construction and reused
        for connection pooling benefits.

        When the transport creates its own session (no ``session`` argument),
        it owns that session and will close/reset it as needed. When an
        external session is injected, the transport does NOT close or reset
        it — the caller retains ownership.

        Callers must call ``close()`` at shutdown to release resources.
        Facades do not call ``close()`` on behalf of the transport.
    """

    def __init__(
        self,
        *,
        default_timeout: float = 30.0,
        default_headers: dict[str, str] | None = None,
        verify_ssl: bool = True,
        pool_connections: int = 10,
        pool_maxsize: int = 20,
        max_retries_transport: int = 0,
        session: requests.Session | None = None,
    ) -> None:
        super().__init__(
            default_timeout=default_timeout,
            default_headers=default_headers,
            verify_ssl=verify_ssl,
        )
        self._pool_connections = pool_connections
        self._pool_maxsize = pool_maxsize
        self._max_retries_transport = max_retries_transport
        self._owns_session = session is None
        self._session = session or SessionFactory.create_requests_session(
            verify_ssl=verify_ssl,
            pool_connections=pool_connections,
            pool_maxsize=pool_maxsize,
            max_retries_transport=max_retries_transport,
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
        proxies = None
        if proxy_url:
            proxies = {"http": proxy_url, "https": proxy_url}

        try:
            response = self._session.request(
                method=method.value,
                url=url,
                headers=headers,
                params=params,
                json=json_body,
                data=data,
                files=files,
                timeout=timeout,
                proxies=proxies,
            )
        except requests.exceptions.Timeout as exc:
            raise TimeoutError(
                f"Request to {url} timed out after {timeout}s",
                timeout_seconds=timeout,
            ) from exc
        except requests.exceptions.ProxyError as exc:
            raise TransportError(
                f"Proxy error for {url}: {exc}",
                details={"proxy_url": proxy_url or ""},
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise TransportError(
                f"Connection error for {url}: {exc}",
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise TransportError(
                f"Request failed for {url}: {exc}",
            ) from exc

        return TransportResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=response.content,
        )

    def reset_session(self) -> None:
        """Close the current session and create a fresh one.

        Only resets sessions owned by this transport. Externally injected
        sessions are not touched — the caller is responsible for those.
        """
        if not self._owns_session:
            return
        self._session.close()
        self._session = SessionFactory.create_requests_session(
            verify_ssl=self._verify_ssl,
            pool_connections=self._pool_connections,
            pool_maxsize=self._pool_maxsize,
            max_retries_transport=self._max_retries_transport,
        )

    def close(self) -> None:
        """Close the underlying requests session."""
        if self._owns_session:
            self._session.close()
