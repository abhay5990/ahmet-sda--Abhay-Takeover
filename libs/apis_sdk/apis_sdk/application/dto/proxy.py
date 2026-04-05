"""
Proxy-related DTOs for the application layer.

These are the public-facing data shapes that use cases
return to consumers, decoupled from internal models.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ProxyPoolStatus:
    """Summary status of the proxy pool."""

    total: int = 0
    healthy: int = 0
    degraded: int = 0
    failed: int = 0
    cooldown: int = 0
    providers: list[str] = field(default_factory=list)

    @property
    def available(self) -> int:
        """Number of proxies available for use (healthy + degraded)."""
        return self.healthy + self.degraded

    @property
    def health_percentage(self) -> float:
        """Percentage of proxies that are healthy."""
        if self.total == 0:
            return 0.0
        return (self.healthy / self.total) * 100.0


@dataclass(frozen=True, slots=True)
class ProxyRefreshResult:
    """Result of a proxy pool refresh operation."""

    provider: str
    fetched: int = 0
    loaded: int = 0
    errors: list[str] = field(default_factory=list)
    success: bool = True
