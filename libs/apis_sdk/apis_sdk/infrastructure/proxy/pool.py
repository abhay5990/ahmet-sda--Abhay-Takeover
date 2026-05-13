"""
Proxy pool — manages a collection of proxies with health-aware selection.

The pool holds ProxyRecord instances and delegates selection to a
pluggable RotationStrategy. It integrates ProxyHealthTracker for
cooldown and failure-threshold behavior, and supports group-based
partitioning (e.g., different proxy groups for different stores).
"""

from __future__ import annotations

import threading
from typing import Sequence

from apis_sdk.core.enums import ProxyStatus
from apis_sdk.core.models import ProxyRecord
from apis_sdk.infrastructure.proxy.health import ProxyHealthTracker
from apis_sdk.infrastructure.proxy.rotation import RotationStrategy, RoundRobinRotation


class ProxyPool:
    """
    Thread-safe proxy pool with integrated health tracking and rotation.

    Health tracking (failure thresholds, cooldown periods, automatic recovery)
    is handled internally via ProxyHealthTracker. The pool uses health state
    to filter candidates during selection.

    Usage:
        pool = ProxyPool(strategy=RoundRobinRotation())
        pool.load(proxy_records)
        proxy = pool.acquire()          # get next healthy proxy
        pool.report_success(proxy)      # mark as healthy
        pool.report_failure(proxy)      # track failure, apply cooldown
    """

    def __init__(
        self,
        *,
        strategy: RotationStrategy | None = None,
        max_failures: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self._lock = threading.Lock()
        self._proxies: list[ProxyRecord] = []
        self._strategy = strategy or RoundRobinRotation()
        self._health = ProxyHealthTracker(
            failure_threshold=max_failures,
            cooldown_seconds=cooldown_seconds,
        )

    def load(self, proxies: Sequence[ProxyRecord]) -> None:
        """Replace the pool contents with a new set of proxies."""
        with self._lock:
            self._proxies = list(proxies)
            self._strategy.reset()

    def add(self, proxy: ProxyRecord) -> None:
        """Add a single proxy to the pool."""
        with self._lock:
            self._proxies.append(proxy)

    def acquire(
        self,
        *,
        group: str | None = None,
        exclude: ProxyRecord | None = None,
    ) -> ProxyRecord | None:
        """
        Select the next healthy proxy from the pool.

        Uses the integrated health tracker to determine availability,
        including cooldown expiry checks.

        Args:
            group: Optional group filter. If provided, only proxies
                   matching this group are considered.
            exclude: Optional proxy to skip. Used during retry flows
                     to avoid immediately reusing a proxy that just failed.

        Returns:
            A ProxyRecord, or None if no healthy proxies are available.
        """
        with self._lock:
            candidates = [
                p for p in self._proxies
                if self._health.is_available_unlocked(p)
                and (group is None or p.group == group)
                and p is not exclude
            ]
            if not candidates:
                return None
            return self._strategy.select(candidates)

    def is_healthy(self, proxy: ProxyRecord) -> bool:
        """Check if a proxy is currently healthy and available for use."""
        with self._lock:
            return self._health.is_available_unlocked(proxy)

    def report_success(self, proxy: ProxyRecord) -> None:
        """Mark a proxy as healthy after successful use."""
        self._health.record_success(proxy)

    def report_failure(self, proxy: ProxyRecord) -> None:
        """Record a failure. Applies cooldown after threshold."""
        self._health.record_failure(proxy)

    @property
    def size(self) -> int:
        """Total number of proxies in the pool."""
        with self._lock:
            return len(self._proxies)

    @property
    def healthy_count(self) -> int:
        """Number of healthy proxies in the pool."""
        with self._lock:
            return sum(1 for p in self._proxies if p.status == ProxyStatus.HEALTHY)

    def get_all(self, *, group: str | None = None) -> list[ProxyRecord]:
        """Return a snapshot of all proxies, optionally filtered by group."""
        with self._lock:
            if group is None:
                return list(self._proxies)
            return [p for p in self._proxies if p.group == group]

    def clear(self) -> None:
        """Remove all proxies from the pool."""
        with self._lock:
            self._proxies.clear()
            self._strategy.reset()

    def get_health_stats(self, proxy: ProxyRecord) -> dict[str, object]:
        """Return health tracking stats for a specific proxy."""
        return self._health.get_stats(proxy)
