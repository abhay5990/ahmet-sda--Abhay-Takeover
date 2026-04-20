"""Base fetcher protocol for additional data sources."""

from __future__ import annotations

from typing import Any, Protocol


class BaseFetcher(Protocol):
    """Protocol for supplemental data fetchers (r6tracker, lzt_refetch, etc.)."""

    def fetch(self, owned_product: Any) -> dict:
        """Fetch additional data for the product. Returns a dict to merge into sources."""
        ...
