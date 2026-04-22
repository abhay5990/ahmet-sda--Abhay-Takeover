"""LZT source provider — fetches items and checks status via LZT SDK."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Generator
from urllib.parse import parse_qs, urlparse

from apps.integrations.providers import registry
from apps.posting.services.dropship.source_provider import (
    DropshipSourceProvider,
    ItemCheckResult,
    register_source,
)

logger = logging.getLogger(__name__)

# Statuses that mean the item is no longer available
_GONE_STATUSES = frozenset({'closed', 'sold', 'deleted', 'paid'})


class LztSourceProvider:
    """DropshipSourceProvider implementation for LZT Market."""

    def __init__(self, *, credential: Any) -> None:
        self._facade = registry.get_or_build_client('lzt', credential)

    # ------------------------------------------------------------------
    # fetch_items
    # ------------------------------------------------------------------

    def fetch_items(
        self,
        url: str,
        *,
        proxy_group: str | None = None,
        max_pages: int = 50,
    ) -> Generator[list[dict[str, Any]], None, None]:
        """Fetch items from an LZT filter URL, yielding pages."""
        category, base_params = _parse_filter_url(url)

        for page_num in range(1, max_pages + 1):
            params = {**base_params, 'page': str(page_num)}

            result = self._facade.get_listings(
                category, params=params, proxy_group=proxy_group,
            )

            if not result.ok:
                logger.warning(
                    "LZT fetch failed for %s page %d: %s",
                    url[:60], page_num, result.error,
                )
                return

            page = result.data
            if not page or not page.items:
                return

            yield page.items

            if not page.has_next_page:
                return

    # ------------------------------------------------------------------
    # check_item
    # ------------------------------------------------------------------

    def check_item(
        self,
        item_id: str,
        *,
        proxy_group: str | None = None,
    ) -> ItemCheckResult:
        """Check a single item's state on LZT."""
        result = self._facade.get_item(item_id, proxy_group=proxy_group)

        if not result.ok:
            # API error — caller handles classification via backoff module
            return ItemCheckResult(
                exists=False,
                status='api_error',
                raw_data={'api_result': result},
            )

        response_data = result.data or {}
        item_data = response_data.get('item', response_data)
        item_status = item_data.get('item_state', item_data.get('status', ''))

        if item_status in _GONE_STATUSES:
            return ItemCheckResult(
                exists=False,
                status=item_status,
                raw_data=item_data,
            )

        price_raw = item_data.get('price', 0)
        current_price = Decimal(str(price_raw)) if price_raw else None

        return ItemCheckResult(
            exists=True,
            status=item_status or 'active',
            current_price=current_price,
            raw_data=item_data,
        )

    # ------------------------------------------------------------------
    # build_source_url
    # ------------------------------------------------------------------

    def build_source_url(self, item_id: str | int) -> str:
        return f"https://lzt.market/{item_id}"

    # ------------------------------------------------------------------
    # extract_item_id
    # ------------------------------------------------------------------

    def extract_item_id(self, item_data: dict[str, Any]) -> str | int:
        item_id = item_data.get('item_id')
        if not item_id:
            raise ValueError("LZT item has no 'item_id' field")
        return item_id


# ---------------------------------------------------------------------------
# URL parsing helper (LZT-specific)
# ---------------------------------------------------------------------------

def _parse_filter_url(url: str) -> tuple[str, dict[str, Any]]:
    """Parse an LZT website filter URL into (category, params).

    Input:  https://lzt.market/fortnite?pmin=5&pmax=50&page=1
    Output: ('fortnite', {'pmin': '5', 'pmax': '50'})
    """
    parsed = urlparse(url)
    path = parsed.path.strip('/')
    category = path.split('/')[0] if path else ''

    if not category:
        raise ValueError(f"Cannot extract category from URL: {url}")

    raw_params = parse_qs(parsed.query)
    params: dict[str, Any] = {}
    for key, values in raw_params.items():
        if key == 'page':
            continue
        params[key] = values[0] if len(values) == 1 else values

    return category, params


# ---------------------------------------------------------------------------
# Auto-register on import
# ---------------------------------------------------------------------------

register_source('lzt', LztSourceProvider)
