"""
Base HTTP transport abstraction.

Provides a concrete base class that implements the HttpTransport protocol
with common functionality (default headers, timeout defaults, pre/post hooks)
that specific transport implementations can extend.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from apis_sdk.core.enums import HttpMethod


@dataclass(slots=True)
class TransportResponse:
    """
    Concrete HTTP response returned by transport implementations.

    Satisfies the HttpResponse protocol from core.
    """

    status_code: int
    headers: dict[str, str]
    body: bytes = b""
    _json: Any = field(default=None, repr=False)

    def json(self) -> Any:
        """Parse response body as JSON."""
        if self._json is not None:
            return self._json
        import json
        self._json = json.loads(self.body)
        return self._json

    @property
    def text(self) -> str:
        """Decode response body as text."""
        return self.body.decode("utf-8", errors="replace")

    @property
    def content(self) -> bytes:
        """Raw response bytes."""
        return self.body

    @property
    def is_success(self) -> bool:
        """Whether status code indicates success (2xx)."""
        return 200 <= self.status_code < 300


class BaseHttpTransport(ABC):
    """
    Abstract base for HTTP transport implementations.

    Provides a template with pre/post hooks and default configuration.
    Subclasses implement _send() with their specific HTTP library.
    """

    def __init__(
        self,
        *,
        default_timeout: float = 30.0,
        default_headers: dict[str, str] | None = None,
        verify_ssl: bool = True,
    ) -> None:
        self._default_timeout = default_timeout
        self._default_headers = default_headers or {}
        self._verify_ssl = verify_ssl

    def request(
        self,
        method: HttpMethod,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        data: Any | None = None,
        files: dict[str, Any] | None = None,
        timeout: float | None = None,
        proxy_url: str | None = None,
    ) -> TransportResponse:
        """
        Execute an HTTP request with merged defaults.

        This is the public entry point. It merges default headers,
        generates a request ID, and delegates to _send().
        """
        merged_headers = {**self._default_headers}
        if headers:
            merged_headers.update(headers)

        if "X-Request-ID" not in merged_headers:
            merged_headers["X-Request-ID"] = uuid.uuid4().hex[:16]

        effective_timeout = timeout if timeout is not None else self._default_timeout

        return self._send(
            method=method,
            url=url,
            headers=merged_headers,
            params=params,
            json_body=json_body,
            data=data,
            files=files,
            timeout=effective_timeout,
            proxy_url=proxy_url,
        )

    @abstractmethod
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
        """
        Send the HTTP request using the underlying library.

        Implementations must translate library-specific errors into
        SDK exceptions (TransportError, TimeoutError).
        """
        ...

    def reset_session(self) -> None:
        """
        Reset the underlying HTTP session.

        Closes the current session and creates a fresh one. This drops
        all connection state (cookies, keep-alive connections, pooled
        sockets) while preserving transport configuration.

        Override in implementations that hold persistent sessions.
        Default is a no-op for transports without session state.
        """

    def close(self) -> None:
        """
        Release transport resources (connection pools, sessions, etc.).

        Override in implementations that hold persistent connections.
        """

    def __enter__(self) -> BaseHttpTransport:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
