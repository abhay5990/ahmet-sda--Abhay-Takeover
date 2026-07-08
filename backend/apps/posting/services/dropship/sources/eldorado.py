"""Eldorado dropship source provider — browses other sellers' item listings."""
from __future__ import annotations
import logging
import time
from typing import Iterator
import requests

logger = logging.getLogger(__name__)

# Eldorado item listing API
ELDORADO_API_BASE = "https://eldorado.gg/api/v1/item-management/offers"
SAB_GAME_ID = 259  # Steal-A-Brainrot game ID on Eldorado


class EldoradoSourceProvider:
    """Browse Eldorado marketplace listings as a dropship source."""

    source_type = "eldorado"

    def __init__(self, credential, proxy_pool=None):
        self._credential = credential
        self._proxy_pool = proxy_pool
        self._session = None

    def _get_session(self):
        if self._session is None:
            self._session = requests.Session()
            # Use stored auth token from credential
            token = None
            if hasattr(self._credential, "token"):
                token = self._credential.token
            elif hasattr(self._credential, "data") and self._credential.data:
                token = self._credential.data.get("token") or self._credential.data.get("access_token")
            if token:
                self._session.headers.update({
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0",
                })
        return self._session

    def fetch_items(self, url: str) -> Iterator[list[dict]]:
        """Fetch pages of items from Eldorado marketplace.
        
        url: query string params e.g. 'gameId=259&category=CustomItem&sortBy=price&sortOrder=asc'
        Yields lists (pages) of raw item dicts.
        """
        session = self._get_session()
        page = 1
        page_size = 20
        while True:
            try:
                params = _parse_query_string(url)
                params.update({"page": page, "pageSize": page_size})
                resp = session.get(ELDORADO_API_BASE, params=params, timeout=15)
                if resp.status_code == 401:
                    logger.warning("Eldorado auth expired for %s", self._credential)
                    break
                resp.raise_for_status()
                data = resp.json()
                items = data.get("offers") or data.get("items") or data.get("data") or []
                if not items:
                    break
                # Normalize: add top-level price key
                for item in items:
                    price_data = item.get("pricePerUnitInUSD") or {}
                    if isinstance(price_data, dict):
                        item["price"] = float(price_data.get("amount", 0) or 0)
                    elif isinstance(price_data, (int, float)):
                        item["price"] = float(price_data)
                yield items
                total = data.get("total") or data.get("totalCount") or 0
                if page * page_size >= total:
                    break
                page += 1
                time.sleep(0.5)
            except Exception as exc:
                logger.error("Eldorado fetch_items error (page %d): %s", page, exc)
                break

    def check_item(self, item_id: str) -> "ItemCheckResult":
        """Check if an Eldorado offer still exists."""
        from apps.posting.services.dropship.source_provider import ItemCheckResult
        session = self._get_session()
        try:
            resp = session.get(f"{ELDORADO_API_BASE}/{item_id}", timeout=10)
            if resp.status_code == 404:
                return ItemCheckResult(exists=False)
            resp.raise_for_status()
            data = resp.json()
            offer = data.get("offer") or data
            status = (offer.get("status") or "").lower()
            exists = status not in ("sold", "deleted", "cancelled", "expired", "inactive")
            return ItemCheckResult(exists=exists)
        except Exception as exc:
            logger.error("Eldorado check_item %s error: %s", item_id, exc)
            return ItemCheckResult(exists=True)  # Assume exists on error

    def extract_item_id(self, item: dict) -> str:
        """Extract the unique item ID from a raw Eldorado offer dict."""
        return str(item.get("id", "") or item.get("offerId", ""))


def _parse_query_string(qs: str) -> dict:
    """Parse a query string like 'gameId=259&category=CustomItem' into a dict."""
    params = {}
    if not qs:
        return params
    if qs.startswith("http"):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(qs)
        for k, v in parse_qs(parsed.query).items():
            params[k] = v[0] if len(v) == 1 else v
        return params
    for part in qs.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k.strip()] = v.strip()
    return params
