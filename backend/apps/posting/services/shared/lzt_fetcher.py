"""LZT filter URL fetch wrapper — parses website URLs into SDK calls."""

from __future__ import annotations

import logging
from typing import Any, Generator
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


def parse_filter_url(url: str) -> tuple[str, dict[str, Any]]:
    """Parse an LZT website filter URL into (category, params).

    Input:  https://lzt.market/fortnite?pmin=5&pmax=50&page=1
    Output: ('fortnite', {'pmin': '5', 'pmax': '50'})

    The 'page' param is stripped — pagination is handled by fetch_items().
    """
    parsed = urlparse(url)

    # Category is the first path segment: /fortnite → fortnite
    path = parsed.path.strip('/')
    category = path.split('/')[0] if path else ''

    if not category:
        raise ValueError(f"Cannot extract category from URL: {url}")

    # Query params — flatten single-value lists
    raw_params = parse_qs(parsed.query)
    params: dict[str, Any] = {}
    for key, values in raw_params.items():
        if key == 'page':
            continue  # pagination handled separately
        params[key] = values[0] if len(values) == 1 else values

    return category, params


def fetch_items(
    lzt_facade: Any,
    url: str,
    *,
    proxy_group: str | None = None,
    max_pages: int = 50,
) -> Generator[list[dict[str, Any]], None, None]:
    """Fetch items from an LZT filter URL, yielding pages.

    Uses LztFacade.get_listings(category, params=) with pagination.
    Yields one list[dict] per page. Stops when has_next_page is False
    or max_pages is reached.
    """
    category, base_params = parse_filter_url(url)

    for page_num in range(1, max_pages + 1):
        params = {**base_params, 'page': str(page_num)}

        result = lzt_facade.get_listings(
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
