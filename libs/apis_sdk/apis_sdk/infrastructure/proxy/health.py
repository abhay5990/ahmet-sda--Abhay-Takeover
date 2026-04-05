"""
Proxy health tracking.

Centralized health state management for proxies, supporting cooldown
periods and failure thresholds. Used by the proxy pool to decide
which proxies are eligible for selection.
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass, field

from apis_sdk.core.models import ProxyRecord
from apis_sdk.core.enums import ProxyStatus


@dataclass(slots=True)
class HealthState:
    """Health tracking state for a single proxy."""

    consecutive_failures: int = 0
    last_failure_time: float = 0.0
    cooldown_until: float = 0.0
    total_requests: int = 0
    total_failures: int = 0


class ProxyHealthTracker:
    """
    Thread-safe health tracker for proxy entries.

    Manages cooldown periods, failure counting, and automatic recovery.

    Usage:
        tracker = ProxyHealthTracker(failure_threshold=3, cooldown_seconds=60.0)
        tracker.record_success(proxy)
        tracker.record_failure(proxy)
        if tracker.is_available(proxy):
            # use proxy
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, HealthState] = {}
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds

    def _key(self, proxy: ProxyRecord) -> str:
        return f"{proxy.host}:{proxy.port}"

    def _get_state(self, proxy: ProxyRecord) -> HealthState:
        key = self._key(proxy)
        if key not in self._states:
            self._states[key] = HealthState()
        return self._states[key]

    def record_success(self, proxy: ProxyRecord) -> None:
        """Record a successful request through this proxy (thread-safe)."""
        with self._lock:
            self._record_success_unlocked(proxy)

    def _record_success_unlocked(self, proxy: ProxyRecord) -> None:
        state = self._get_state(proxy)
        state.consecutive_failures = 0
        state.total_requests += 1
        state.cooldown_until = 0.0
        proxy.mark_healthy()

    def record_failure(self, proxy: ProxyRecord) -> None:
        """Record a failed request through this proxy (thread-safe)."""
        with self._lock:
            self._record_failure_unlocked(proxy)

    def _record_failure_unlocked(self, proxy: ProxyRecord) -> None:
        state = self._get_state(proxy)
        state.consecutive_failures += 1
        state.total_failures += 1
        state.total_requests += 1
        state.last_failure_time = time.monotonic()

        if state.consecutive_failures >= self._failure_threshold:
            state.cooldown_until = time.monotonic() + self._cooldown_seconds
            proxy.status = ProxyStatus.COOLDOWN
        else:
            proxy.mark_failed()

    def is_available(self, proxy: ProxyRecord) -> bool:
        """Check if a proxy is currently available for use (thread-safe)."""
        with self._lock:
            return self._is_available_unlocked(proxy)

    def is_available_unlocked(self, proxy: ProxyRecord) -> bool:
        """Check availability without acquiring lock.

        Used by ProxyPool which already holds its own lock and coordinates
        access to both the proxy list and the health tracker.
        """
        return self._is_available_unlocked(proxy)

    def _is_available_unlocked(self, proxy: ProxyRecord) -> bool:
        state = self._get_state(proxy)
        now = time.monotonic()

        # If in cooldown, check if cooldown has expired
        if state.cooldown_until > 0 and now < state.cooldown_until:
            return False

        # Cooldown expired — reset and allow
        if state.cooldown_until > 0 and now >= state.cooldown_until:
            state.consecutive_failures = 0
            state.cooldown_until = 0.0
            proxy.mark_healthy()

        return proxy.status in (ProxyStatus.HEALTHY, ProxyStatus.DEGRADED)

    def get_stats(self, proxy: ProxyRecord) -> dict[str, object]:
        """Return health stats for a proxy."""
        with self._lock:
            state = self._get_state(proxy)
            return {
                "consecutive_failures": state.consecutive_failures,
                "total_requests": state.total_requests,
                "total_failures": state.total_failures,
                "in_cooldown": time.monotonic() < state.cooldown_until,
            }
