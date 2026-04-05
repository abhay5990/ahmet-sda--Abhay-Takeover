"""
Proxy rotation strategies.

Pluggable selection algorithms for choosing the next proxy from a pool.
The pool delegates to a strategy so consumers can swap behavior
(round-robin, random, least-used, weighted) without changing pool code.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod

from apis_sdk.core.models import ProxyRecord


class RotationStrategy(ABC):
    """Abstract strategy for proxy selection."""

    @abstractmethod
    def select(self, candidates: list[ProxyRecord]) -> ProxyRecord:
        """
        Choose one proxy from the list of healthy candidates.

        The candidates list is guaranteed non-empty by the pool.
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """Reset internal state (called when pool is reloaded)."""
        ...


class RoundRobinRotation(RotationStrategy):
    """Cycle through proxies in order, wrapping at the end."""

    def __init__(self) -> None:
        self._index = 0

    def select(self, candidates: list[ProxyRecord]) -> ProxyRecord:
        idx = self._index % len(candidates)
        self._index = idx + 1
        return candidates[idx]

    def reset(self) -> None:
        self._index = 0


class RandomRotation(RotationStrategy):
    """Select a random proxy each time."""

    def select(self, candidates: list[ProxyRecord]) -> ProxyRecord:
        return random.choice(candidates)

    def reset(self) -> None:
        pass


class LeastFailuresRotation(RotationStrategy):
    """Prefer proxies with the fewest recorded failures."""

    def select(self, candidates: list[ProxyRecord]) -> ProxyRecord:
        return min(candidates, key=lambda p: p.failure_count)

    def reset(self) -> None:
        pass
