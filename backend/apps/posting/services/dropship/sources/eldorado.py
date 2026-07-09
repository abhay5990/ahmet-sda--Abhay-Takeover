"""Eldorado dropship source provider — browses other sellers' item listings."""
from __future__ import annotations
import logging
import time
from typing import Iterator
import requests

logger = logging.getLogger(__name__)
from apps.posting.services.dropship.source_provider import register_source  # noqa: E402

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

    def fetch_items(self, url: str, seller_username: str = "", proxy_group=None) -> Iterator[list[dict]]:
        """Fetch pages of items from Eldorado marketplace.

        url: query string params or full URL
             e.g. 'gameId=259&category=CustomItem&sortBy=price&sortOrder=asc'
             or   'https://www.eldorado.gg/users/OdbougShop/shop/CustomItem?gameId=259'

        seller_username: if set, only items from this seller are yielded.
                         The Eldorado API does not support server-side seller filtering,
                         so we fetch all pages and filter client-side by
                         item["user"]["username"].

        Yields lists (pages) of raw item dicts.
        """
        session = self._get_session()

        # Detect seller-shop URL pattern and extract seller from path if not explicitly given
        if not seller_username:
            seller_username = _extract_seller_from_url(url)

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

                raw_items = data.get("results") or data.get("offers") or data.get("items") or data.get("data") or []
                if not raw_items:
                    break

                # Normalize each result — Eldorado wraps items in {"offer": {...}, "user": {...}}
                normalized = []
                for entry in raw_items:
                    item = _normalize_item(entry)
                    if not item:
                        continue
                    # Client-side seller filter
                    if seller_username:
                        item_seller = (item.get("_seller_username") or "").lower()
                        if item_seller != seller_username.lower():
                            continue
                    normalized.append(item)

                if normalized:
                    yield normalized

                # Pagination
                total_pages = data.get("totalPages") or 0
                record_count = data.get("recordCount") or 0
                if total_pages:
                    if page >= total_pages:
                        break
                elif record_count:
                    if page * page_size >= record_count:
                        break
                else:
                    break

                page += 1
                time.sleep(0.5)

            except Exception as exc:
                logger.error("Eldorado fetch_items error (page %d): %s", page, exc)
                break

    def fetch_seller_profile(self, seller_username: str) -> dict | None:
        """Fetch public seller profile info from Eldorado.

        Returns dict with keys: username, rating, completedOrders, isVerifiedSeller, etc.
        Returns None if not found or on error.
        """
        session = self._get_session()
        try:
            # Try the seller's shop endpoint to get their profile from the first item's user object
            resp = session.get(
                ELDORADO_API_BASE,
                params={"pageSize": 1, "page": 1},
                timeout=10,
            )
            if not resp.ok:
                return None
            data = resp.json()
            results = data.get("results") or []
            for entry in results:
                user = entry.get("user") or {}
                uname = user.get("username") or ""
                if uname.lower() == seller_username.lower():
                    return _parse_seller_profile(user)
            # Not found in first page — return minimal info
            return {"username": seller_username, "found": False}
        except Exception as exc:
            logger.warning("fetch_seller_profile %s error: %s", seller_username, exc)
            return None

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

    def build_source_url(self, item_id: str) -> str:
        """Build a source URL for the given item ID (for internal reference only)."""
        return f"eldorado:{item_id}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_item(entry: dict) -> dict | None:
    """Normalize an Eldorado API result entry.

    The API wraps items as:
        {"offer": {...}, "user": {...}, "userOrderInfo": {...}, "deliveryTime": {...}}

    We flatten this into a single dict that the rest of the pipeline expects,
    preserving the original structure under "offer" and "user" keys.
    """
    if not entry:
        return None

    offer = entry.get("offer") or {}
    user = entry.get("user") or {}

    # Support both wrapped (new API) and flat (old API) formats
    if not offer and "id" not in entry and "offerId" not in entry:
        return None

    # Build flat item dict compatible with SabEldoradoSourceAdapter
    if offer:
        item = dict(offer)
        item["_seller_username"] = user.get("username") or ""
        item["_seller_id"] = user.get("id") or ""
        item["_seller_verified"] = user.get("isVerifiedSeller") or False
        item["_seller_rating"] = user.get("rating") or 0
        item["_user_order_info"] = entry.get("userOrderInfo") or {}
        item["_delivery_time"] = entry.get("deliveryTime") or {}

        # Normalize price field for downstream compatibility
        price_data = item.get("minPurchasePrice") or item.get("pricePerUnitInUSD") or {}
        if isinstance(price_data, dict):
            item["price"] = float(price_data.get("amount", 0) or 0)
            item["price_currency"] = price_data.get("currency", "USD")
        elif isinstance(price_data, (int, float)):
            item["price"] = float(price_data)

        # Normalize offer ID
        if "id" not in item:
            item["id"] = item.get("offerId") or ""

        # Normalize title
        if "title" not in item:
            item["title"] = item.get("offerTitle") or ""

        # Normalize tradeEnvironmentValues for SabEldoradoSourceAdapter
        if "tradeEnvironmentValues" not in item:
            item["tradeEnvironmentValues"] = []

        return item
    else:
        # Flat format (legacy) — add seller fields if missing
        entry["_seller_username"] = entry.get("_seller_username") or ""
        price_data = entry.get("pricePerUnitInUSD") or {}
        if isinstance(price_data, dict):
            entry["price"] = float(price_data.get("amount", 0) or 0)
        elif isinstance(price_data, (int, float)):
            entry["price"] = float(price_data)
        return entry


def _parse_seller_profile(user: dict) -> dict:
    """Extract relevant seller profile fields from a user object."""
    return {
        "username": user.get("username") or "",
        "id": user.get("id") or "",
        "isVerifiedSeller": user.get("isVerifiedSeller") or False,
        "rating": user.get("rating") or 0,
        "description": (user.get("description") or "")[:200],
        "createdDate": user.get("createdDate") or "",
        "found": True,
    }


def _extract_seller_from_url(url: str) -> str:
    """Extract seller username from a shop URL path.

    e.g. https://www.eldorado.gg/users/OdbougShop/shop/CustomItem?gameId=259
    → 'OdbougShop'
    """
    if not url or not url.startswith("http"):
        return ""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        parts = parsed.path.strip("/").split("/")
        # Pattern: /users/{username}/shop/...
        if len(parts) >= 2 and parts[0] == "users":
            return parts[1]
    except Exception:
        pass
    return ""


def _parse_query_string(qs: str) -> dict:
    """Parse a query string like 'gameId=259&category=CustomItem' into a dict.

    Also handles full URLs — extracts only the query string params.
    The path (e.g. /users/OdbougShop/shop/CustomItem) is intentionally ignored
    because the Eldorado API does not support path-based seller filtering.
    Seller filtering is done client-side via seller_username param.
    """
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
register_source("eldorado", EldoradoSourceProvider)
