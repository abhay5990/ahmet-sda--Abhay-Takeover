"""Eldorado dropship source provider — browses other sellers' item listings."""
from __future__ import annotations
import logging
import time
from typing import Iterator

# Use curl_cffi for browser TLS impersonation — Cloudflare blocks plain
# Python requests.Session() when running as a system service (different
# network/TLS fingerprint context). curl_cffi mimics Chrome's TLS handshake
# and bypasses Cloudflare bot protection reliably.
try:
    from curl_cffi import requests as cffi_requests
    _USE_CURL_CFFI = True
except ImportError:
    import requests as cffi_requests  # type: ignore[no-redef]
    _USE_CURL_CFFI = False

logger = logging.getLogger(__name__)

from apps.posting.services.dropship.source_provider import register_source  # noqa: E402

# Eldorado item listing API
ELDORADO_API_BASE = "https://www.eldorado.gg/api/v1/item-management/offers"
SAB_GAME_ID = 259  # Steal-A-Brainrot game ID on Eldorado

# Browser impersonation target for curl_cffi
_IMPERSONATE = "chrome124"

# In-memory cache: seller_username.lower() → userId UUID
# Populated lazily on first fetch; persists for the lifetime of the process.
_SELLER_UUID_CACHE: dict[str, str] = {}


class EldoradoSourceProvider:
    """Browse Eldorado marketplace listings as a dropship source."""

    source_type = "eldorado"

    def __init__(self, credential, proxy_pool=None):
        self._credential = credential
        self._proxy_pool = proxy_pool
        self._session = None

    def _get_session(self):
        if self._session is None:
            if _USE_CURL_CFFI:
                # curl_cffi Session with Chrome TLS fingerprint — bypasses Cloudflare
                self._session = cffi_requests.Session(impersonate=_IMPERSONATE)
            else:
                import requests
                self._session = requests.Session()

            # Apply auth token if available
            token = None
            if hasattr(self._credential, "token"):
                token = self._credential.token
            elif hasattr(self._credential, "data") and self._credential.data:
                token = self._credential.data.get("token") or self._credential.data.get("access_token")
            if token:
                self._session.headers.update({
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                })
        return self._session

    def _resolve_seller_uuid(self, seller_username: str) -> str | None:
        """Resolve a seller username to their Eldorado userId UUID.

        Strategy (fastest first):
        1. In-memory cache — instant if already resolved this process lifetime.
        2. DB cache — check DropshipTargetURL.seller_uuid for pre-saved UUIDs.
        3. Profile page scrape — fetch /users/{username}/shop and extract the
           UUID from the seller's avatar image URL (format:
           /_profiles-v2_/{UUID}_Avatar_...). This is O(1) — one HTTP request.
        4. Listing scan fallback — scan up to 50 pages of recent listings to
           find an item from this seller and extract their UUID. Slow but works
           even if the profile page is unavailable.

        Returns the UUID string, or None if all methods fail.
        """
        import re as _re
        key = seller_username.lower()
        if key in _SELLER_UUID_CACHE:
            return _SELLER_UUID_CACHE[key]

        logger.info("Resolving Eldorado UUID for seller '%s'...", seller_username)
        session = self._get_session()

        # --- Method 1: DB cache (DropshipTargetURL.seller_uuid) ---
        try:
            from apps.posting.models import DropshipTargetURL
            db_uuid = (
                DropshipTargetURL.objects
                .filter(seller_username__iexact=seller_username)
                .exclude(seller_uuid="")
                .values_list("seller_uuid", flat=True)
                .first()
            )
            if db_uuid:
                _SELLER_UUID_CACHE[key] = db_uuid
                logger.info(
                    "Resolved seller '%s' -> UUID %s (from DB cache)",
                    seller_username, db_uuid,
                )
                return db_uuid
        except Exception as exc:
            logger.debug("DB cache lookup failed for '%s': %s", seller_username, exc)

        # --- Method 2: Profile page scrape ---
        # The seller's avatar URL on Eldorado contains their UUID:
        #   https://assetsdelivery.eldorado.gg/v7/_profiles-v2_/{UUID}_Avatar_...
        # We fetch the seller's shop page (server-rendered HTML includes the
        # avatar URL in the initial page source) and regex out the UUID.
        try:
            resp2 = session.get(
                f"https://www.eldorado.gg/users/{seller_username}/shop",
                timeout=10,
            )
            if resp2.ok:
                uuid_pat = _re.compile(
                    r"_profiles-v2_/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})_Avatar_",
                    _re.IGNORECASE,
                )
                m = uuid_pat.search(resp2.text)
                if m:
                    uid = m.group(1)
                    _SELLER_UUID_CACHE[key] = uid
                    # Persist to DB for future processes
                    try:
                        from apps.posting.models import DropshipTargetURL
                        DropshipTargetURL.objects.filter(
                            seller_username__iexact=seller_username,
                        ).exclude(seller_uuid=uid).update(seller_uuid=uid)
                    except Exception:
                        pass
                    logger.info(
                        "Resolved seller '%s' -> UUID %s (profile page scrape)",
                        seller_username, uid,
                    )
                    return uid
        except Exception as exc:
            logger.debug("Profile page scrape failed for '%s': %s", seller_username, exc)

        # --- Method 3: Listing scan fallback ---
        # Scan up to 50 pages of recent listings to find an item from this seller.
        for page in range(1, 51):
            try:
                resp = session.get(
                    ELDORADO_API_BASE,
                    params={
                        "gameId": SAB_GAME_ID,
                        "category": "CustomItem",
                        "sortBy": "date",
                        "sortOrder": "desc",
                        "page": page,
                        "pageSize": 20,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                results = data.get("results") or []
                for entry in results:
                    user = entry.get("user") or {}
                    uname = (user.get("username") or "").lower()
                    uid = user.get("id") or ""
                    # Cache every seller we encounter along the way
                    if uname and uid:
                        _SELLER_UUID_CACHE[uname] = uid
                    if uname == key and uid:
                        logger.info(
                            "Resolved seller '%s' -> UUID %s (found on page %d)",
                            seller_username, uid, page,
                        )
                        return uid
                if not results:
                    break
                time.sleep(0.3)
            except Exception as exc:
                logger.warning("UUID resolve error (page %d): %s", page, exc)
                break

        logger.warning(
            "Could not resolve UUID for seller '%s' within scan limit -- "
            "falling back to client-side filtering",
            seller_username,
        )
        return None

    def fetch_items(self, url: str, seller_username: str = "", proxy_group=None) -> Iterator[list[dict]]:
        """Fetch pages of items from Eldorado marketplace.

        url: query string params or full URL
             e.g. 'gameId=259&category=CustomItem&sortBy=price&sortOrder=asc'
             or   'https://www.eldorado.gg/users/OdbougShop/shop/CustomItem?gameId=259'

        seller_username: if set, only items from this seller are yielded.
            Strategy:
            1. Resolve the seller's userId UUID (cached after first lookup).
            2. Pass ``userId={UUID}`` as a query param → server-side filter,
               returns ONLY that seller's items (typically 1–2 pages).
            3. If UUID resolution fails, fall back to client-side filtering
               (scans all pages — slow, but correct).

        Important: Eldorado's ``userId`` filter returns 0 results when combined
        with ``gameId``, so seller fetches drop ``gameId`` server-side and
        re-apply game/category filters client-side. Without that, a multi-game
        seller's non-SAB offers would be dropshipped as SAB items.

        Yields lists (pages) of raw item dicts.
        """
        session = self._get_session()

        # Detect seller-shop URL pattern and extract seller from path if not explicitly given
        if not seller_username:
            seller_username = _extract_seller_from_url(url)

        url_params = _parse_query_string(url)
        expected_game_id = _coerce_game_id(
            url_params.get("gameId") or url_params.get("game_id")
        )
        # SAB item dropship configs always target game 259. Default to SAB when
        # the URL omits gameId so seller-UUID fetches cannot leak other games.
        if expected_game_id is None:
            expected_game_id = SAB_GAME_ID
        expected_category = (url_params.get("category") or "").strip()

        # userId filter works WITHOUT gameId. Use it for seller-specific fetches (1 page).
        # With gameId, userId filter returns 0. Without gameId, it returns seller items correctly.
        seller_uuid: str | None = None
        if seller_username:
            seller_uuid = self._resolve_seller_uuid(seller_username)
            if seller_uuid:
                logger.info(
                    "Server-side userId filter for seller %s (UUID: %s, "
                    "client-side gameId=%s category=%s)",
                    seller_username, seller_uuid, expected_game_id, expected_category or "*",
                )
            else:
                logger.warning(
                    "Could not resolve UUID for %s, using client-side scan",
                    seller_username,
                )
        page = 1
        page_size = 50
        while True:
            try:
                if seller_uuid:
                    # Drop gameId — it breaks the userId filter. Game/category
                    # are enforced client-side below after normalization.
                    params = {"userId": seller_uuid, "page": page, "pageSize": page_size}
                else:
                    params = dict(url_params)
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
                skipped_wrong_game = 0
                for entry in raw_items:
                    item = _normalize_item(entry)
                    if not item:
                        continue
                    # Client-side seller filter (only when UUID not resolved)
                    if seller_username and not seller_uuid:
                        item_seller = (item.get("_seller_username") or "").lower()
                        if item_seller != seller_username.lower():
                            continue
                    # Always enforce game/category. Critical for seller-UUID
                    # fetches which must omit gameId on the API request.
                    if not _item_matches_filters(
                        item,
                        expected_game_id=expected_game_id,
                        expected_category=expected_category,
                    ):
                        skipped_wrong_game += 1
                        continue
                    normalized.append(item)

                if skipped_wrong_game:
                    logger.info(
                        "Eldorado page %d: skipped %d non-matching items "
                        "(gameId=%s category=%s) for seller '%s'",
                        page, skipped_wrong_game, expected_game_id,
                        expected_category or "*", seller_username or "all",
                    )

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
                if page % 100 == 0:
                    logger.info("Eldorado scan progress: page %d / ~1200 for seller '%s'", page, seller_username or "all")
                time.sleep(0.5)
            except Exception as exc:
                logger.error("Eldorado fetch_items error (page %d): %s", page, exc)
                break

    def fetch_seller_profile(self, seller_username: str) -> dict | None:
        """Fetch public seller profile info from Eldorado.

        Returns dict with keys: username, rating, completedOrders, isVerifiedSeller, etc.
        Scans the first few pages of SAB listings to find the seller.
        """
        session = self._get_session()
        try:
            for page in range(1, 4):
                resp = session.get(
                    ELDORADO_API_BASE,
                    params={
                        "gameId": SAB_GAME_ID,
                        "category": "CustomItem",
                        "pageSize": 20,
                        "page": page,
                    },
                    timeout=10,
                )
                if not resp.ok:
                    break
                data = resp.json()
                results = data.get("results") or []
                for entry in results:
                    user = entry.get("user") or {}
                    uname = (user.get("username") or "").lower()
                    if uname == seller_username.lower():
                        return _parse_seller_profile(user)
            return {"username": seller_username, "found": False}
        except Exception as exc:
            logger.warning("fetch_seller_profile %s error: %s", seller_username, exc)
            return None

    def check_item(self, item_id: str, *, proxy_group=None):
        """Check if an Eldorado item still exists and get its current price."""
        from apps.posting.services.dropship.source_provider import ItemCheckResult
        from decimal import Decimal

        session = self._get_session()
        try:
            resp = session.get(
                f"{ELDORADO_API_BASE}/{item_id}",
                timeout=10,
            )
            if resp.status_code == 404:
                return ItemCheckResult(exists=False, status="not_found")
            if not resp.ok:
                logger.warning("check_item %s: HTTP %d", item_id, resp.status_code)
                return ItemCheckResult(exists=True)  # Assume exists on error
            data = resp.json()
            offer = data.get("offer") or data
            state = (offer.get("offerState") or "").lower()
            if state in ("inactive", "deleted", "sold"):
                return ItemCheckResult(exists=False, status=state)
            price_data = offer.get("minPurchasePrice") or offer.get("pricePerUnitInUSD") or {}
            price = None
            if isinstance(price_data, dict):
                amt = price_data.get("amount")
                if amt is not None:
                    price = Decimal(str(amt))
            return ItemCheckResult(
                exists=True,
                status=state or "active",
                current_price=price,
                raw_data=data,
            )
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


def _coerce_game_id(value) -> int | None:
    """Parse a gameId query/API value to int, or None if missing/invalid."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _item_matches_filters(
    item: dict,
    *,
    expected_game_id: int | None,
    expected_category: str = "",
) -> bool:
    """Return True when the normalized offer matches configured game/category.

    Used after seller-UUID fetches (which cannot send gameId server-side) so
    non-SAB offers from multi-game sellers are never dropshipped as SAB items.
    """
    if expected_game_id is not None:
        item_game_id = _coerce_game_id(item.get("gameId") or item.get("game_id"))
        if item_game_id is None or item_game_id != expected_game_id:
            return False
    if expected_category:
        item_category = (
            item.get("category")
            or item.get("offerCategory")
            or item.get("listingCategory")
            or ""
        )
        if str(item_category).strip().lower() != expected_category.lower():
            return False
    return True


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
    Seller filtering is done via userId UUID (server-side) or client-side fallback.
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
