"""
Rate limiter implementations.

Provides token-bucket / sliding-window rate limiting that clients
use to throttle outgoing requests per provider. Designed to be
injectable — clients receive a limiter instance, they don't create one.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod


class RateLimiter(ABC):
    """Abstract rate limiter protocol."""

    @abstractmethod
    def acquire(self, *, key: str = "default") -> float:
        """
        Acquire permission to proceed.

        Returns the number of seconds the caller should wait
        before making the request. Returns 0.0 if no wait is needed.
        Implementations may also block internally.
        """
        ...

    @abstractmethod
    def remaining(self, *, key: str = "default") -> int:
        """Return the number of requests remaining in the current window."""
        ...


class InMemoryRateLimiter(RateLimiter):
    """
    Thread-safe in-memory sliding window rate limiter.

    Suitable for single-process deployments. For multi-process
    scenarios, use a Redis-backed implementation.

    Usage:
        limiter = InMemoryRateLimiter(max_requests=200, window_seconds=60.0)
        wait = limiter.acquire(key="eldorado")
        if wait > 0:
            time.sleep(wait)
    """

    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: float,
    ) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._lock = threading.Lock()
        self._timestamps: dict[str, list[float]] = {}

    def acquire(self, *, key: str = "default") -> float:
        with self._lock:
            now = time.monotonic()
            if key not in self._timestamps:
                self._timestamps[key] = []

            # Prune expired timestamps
            window_start = now - self._window_seconds
            self._timestamps[key] = [
                t for t in self._timestamps[key] if t > window_start
            ]

            if len(self._timestamps[key]) < self._max_requests:
                self._timestamps[key].append(now)
                return 0.0

            # Need to wait until the oldest timestamp exits the window
            oldest = self._timestamps[key][0]
            wait_time = oldest + self._window_seconds - now
            return max(0.0, wait_time)

    def remaining(self, *, key: str = "default") -> int:
        with self._lock:
            now = time.monotonic()
            window_start = now - self._window_seconds
            if key not in self._timestamps:
                return self._max_requests
            active = [t for t in self._timestamps[key] if t > window_start]
            return max(0, self._max_requests - len(active))
