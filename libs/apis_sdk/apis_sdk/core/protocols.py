"""
Core protocols (interfaces) for the SDK.

Protocols define the contracts that infrastructure and client layers implement.
Using Protocol instead of ABC enables structural subtyping — implementations
don't need to explicitly inherit, they just need to match the shape.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from apis_sdk.core.enums import HttpMethod, ProxyProtocol
from apis_sdk.core.result import ApiResult


@runtime_checkable
class HttpTransport(Protocol):
    """
    Protocol for HTTP transport implementations.

    The SDK ships with a requests-based implementation, but consumers
    can provide their own (httpx, aiohttp, etc.) by matching this protocol.
    """

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
    ) -> HttpResponse:
        """Execute an HTTP request and return a transport-level response."""
        ...

    def close(self) -> None:
        """Release transport resources."""
        ...


@runtime_checkable
class HttpResponse(Protocol):
    """
    Protocol for HTTP response objects returned by transports.

    Keeps the SDK decoupled from any specific HTTP library's response type.
    """

    @property
    def status_code(self) -> int: ...

    @property
    def headers(self) -> dict[str, str]: ...

    def json(self) -> Any: ...

    @property
    def text(self) -> str: ...

    @property
    def content(self) -> bytes: ...

    @property
    def is_success(self) -> bool: ...


@runtime_checkable
class AuthProvider(Protocol):
    """
    Protocol for authentication providers.

    Each marketplace may have a different auth mechanism (Bearer token,
    Cognito SRP, OAuth2, etc.). The AuthProvider abstracts over all of them.
    """

    def get_auth_headers(self) -> dict[str, str]:
        """Return headers required for authenticated requests."""
        ...

    def refresh(self) -> bool:
        """
        Attempt to refresh credentials.

        Returns True if refresh succeeded, False otherwise.
        """
        ...

    @property
    def is_expired(self) -> bool:
        """Whether the current credentials need refreshing."""
        ...


@runtime_checkable
class ProxyProvider(Protocol):
    """
    Protocol for proxy provider clients (Proxyline, DataImpulse, etc.).

    Provider clients fetch proxy lists from external APIs.
    This is separate from the proxy *pool/rotation engine* in infrastructure.
    """

    def list_proxies(self) -> ApiResult[list[ProxyEntry]]:
        """Fetch available proxies from the provider."""
        ...

    @property
    def provider_name(self) -> str:
        """Identifier for this proxy provider (e.g., 'proxyline')."""
        ...


@runtime_checkable
class ProxyEntry(Protocol):
    """
    Protocol for a single proxy entry.

    Implementations may be dataclasses, pydantic models, or plain objects
    as long as they expose these attributes.
    """

    @property
    def host(self) -> str: ...

    @property
    def port(self) -> int: ...

    @property
    def protocol(self) -> ProxyProtocol | str: ...

    @property
    def username(self) -> str | None: ...

    @property
    def password(self) -> str | None: ...

    def to_url(self) -> str:
        """Format as proxy URL (e.g., 'http://user:pass@host:port')."""
        ...


@runtime_checkable
class ProxyPoolRuntime(Protocol):
    """
    Protocol for runtime proxy pool implementations.

    Application use-cases should depend on this contract instead of
    concrete infrastructure classes.
    """

    def clear(self) -> None:
        """Remove all proxies from the runtime pool."""
        ...

    def add(self, proxy: ProxyEntry) -> None:
        """Add one proxy entry to the runtime pool."""
        ...

    def acquire(self, *, group: str | None = None) -> ProxyEntry | None:
        """Select the next available proxy, optionally filtered by group."""
        ...

    def report_success(self, proxy: ProxyEntry) -> None:
        """Report successful use of a proxy."""
        ...

    def report_failure(self, proxy: ProxyEntry) -> None:
        """Report failed use of a proxy."""
        ...

    @property
    def size(self) -> int:
        """Total entries currently in the pool."""
        ...

    @property
    def healthy_count(self) -> int:
        """Number of healthy entries currently in the pool."""
        ...
