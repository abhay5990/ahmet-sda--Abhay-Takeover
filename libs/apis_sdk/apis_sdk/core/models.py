"""
Core data models shared across the SDK.

These are simple, framework-agnostic data containers.
Provider-specific models live in their respective client modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apis_sdk.core.enums import ProxyProtocol, ProxyStatus


@dataclass(slots=True)
class ProxyRecord:
    """
    A resolved proxy entry ready for use by the proxy pool.

    This is the SDK's canonical proxy representation, independent of
    any specific provider's API response format. Provider clients map
    their responses into ProxyRecord via mappers.
    """

    host: str
    port: int
    protocol: ProxyProtocol = ProxyProtocol.HTTP
    username: str | None = None
    password: str | None = None
    provider: str = ""
    group: str = ""
    status: ProxyStatus = ProxyStatus.HEALTHY
    failure_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_url(self) -> str:
        """Format as a proxy URL suitable for HTTP clients."""
        scheme = self.protocol.value
        if self.username and self.password:
            return f"{scheme}://{self.username}:{self.password}@{self.host}:{self.port}"
        return f"{scheme}://{self.host}:{self.port}"

    def mark_failed(self) -> None:
        """Record a failure and update status accordingly."""
        self.failure_count += 1
        if self.failure_count >= 3:
            self.status = ProxyStatus.FAILED
        else:
            self.status = ProxyStatus.DEGRADED

    def mark_healthy(self) -> None:
        """Reset to healthy after successful use."""
        self.failure_count = 0
        self.status = ProxyStatus.HEALTHY


@dataclass(frozen=True, slots=True)
class RequestContext:
    """
    Metadata about an outgoing request, passed through the transport chain.

    Used for logging, metrics, and retry decisions. Not sent to the provider.
    """

    provider: str = ""
    operation: str = ""
    request_id: str = ""
    attempt: int = 1
    max_attempts: int = 3
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PaginationInfo:
    """Standard pagination metadata returned by paginated endpoints."""

    page: int = 1
    per_page: int = 20
    total_items: int | None = None
    total_pages: int | None = None
    has_next: bool = False

    @property
    def next_page(self) -> int | None:
        """Return the next page number, or None if at the end."""
        if self.has_next:
            return self.page + 1
        return None
