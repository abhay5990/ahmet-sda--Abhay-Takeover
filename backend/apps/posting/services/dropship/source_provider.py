"""DropshipSourceProvider — generic interface for source platforms.

Decouples poster/cleaner from any specific source marketplace (LZT, etc.).
New platforms register via ``register_source()``; poster/cleaner call
``get_source_provider()`` to get the right implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Generator, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Data contract — check_item() return type
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ItemCheckResult:
    """Result of checking a single source item's current state."""

    exists: bool
    status: str = ''
    current_price: Decimal | None = None
    raw_data: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Protocol — source platform interface
# ---------------------------------------------------------------------------

@runtime_checkable
class DropshipSourceProvider(Protocol):
    """Interface every source platform must implement.

    Implementations live in ``posting/services/dropship/sources/<name>.py``.
    """

    def fetch_items(
        self,
        url: str,
        *,
        proxy_group: str | None = None,
        max_pages: int = 50,
    ) -> Generator[list[dict[str, Any]], None, None]:
        """Yield pages of items from a filter URL.

        Each page is a list of raw item dicts as returned by the source API.
        """
        ...

    def check_item(
        self,
        item_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ItemCheckResult:
        """Check the current state of a single item on the source platform."""
        ...

    def build_source_url(self, item_id: str | int) -> str:
        """Build the canonical URL for an item on the source platform."""
        ...

    def extract_item_id(self, item_data: dict[str, Any]) -> str | int:
        """Extract the source item ID from a raw item dict."""
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[DropshipSourceProvider]] = {}


def register_source(provider_name: str, cls: type[DropshipSourceProvider]) -> None:
    """Register a source provider class for a given provider name."""
    _REGISTRY[provider_name] = cls


def get_source_provider(
    provider_name: str,
    credential: Any,
    *,
    proxy_pool: Any | None = None,
) -> DropshipSourceProvider:
    """Instantiate and return the source provider for *provider_name*.

    Args:
        provider_name: Matches ``IntegrationAccount.provider`` (e.g. ``'lzt'``).
        credential: The credential object passed to the provider constructor.
        proxy_pool: Optional SDK ProxyPool for proxy-group-based routing.

    Raises:
        KeyError: If no provider is registered for *provider_name*.
    """
    cls = _REGISTRY.get(provider_name)
    if cls is None:
        registered = ', '.join(sorted(_REGISTRY)) or '(none)'
        raise KeyError(
            f"No DropshipSourceProvider registered for '{provider_name}'. "
            f"Registered: {registered}"
        )
    return cls(credential=credential, proxy_pool=proxy_pool)
