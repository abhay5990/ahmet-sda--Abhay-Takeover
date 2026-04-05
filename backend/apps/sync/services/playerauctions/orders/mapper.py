from __future__ import annotations

import re
from datetime import datetime, timezone

from apps.orders.enums import OrderStatus
from core.enums import ProductCategory

# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------

# PlayerAuctions list endpoint returns plain string statuses.
# Detail endpoint returns a nested status object with ``current`` field.
# We normalize both paths through the same map.

PA_STATUS_MAP = {
    # Pending / in-progress
    'pending payment': OrderStatus.PENDING,
    'payment received': OrderStatus.PENDING,
    'order processing': OrderStatus.PENDING,
    'delivery in progress': OrderStatus.PENDING,
    'verifying payment': OrderStatus.PENDING,
    # Completed
    'delivery fully completed': OrderStatus.COMPLETED,
    'completed': OrderStatus.COMPLETED,
    'disputed delivery fully completed': OrderStatus.COMPLETED,
    # Cancelled / terminated
    'cancelled': OrderStatus.CANCELLED,
    'seller cancelled': OrderStatus.CANCELLED,
    'order terminated': OrderStatus.CANCELLED,
    'delivery expired': OrderStatus.CANCELLED,
    # Refunded
    'refunded': OrderStatus.REFUNDED,
    # Disputed
    'disputed': OrderStatus.DISPUTED,
    'disputed delivery not completed': OrderStatus.DISPUTED,
    'disputed delivery completed': OrderStatus.DISPUTED,
    'disputed delivery partially completed': OrderStatus.DISPUTED,
}


def map_status(status_str: str) -> str:
    """Map a PlayerAuctions status string to OrderStatus.

    Performs case-insensitive matching against known status values.
    Falls back to PENDING for unknown statuses.
    """
    if not status_str:
        return OrderStatus.PENDING
    return PA_STATUS_MAP.get(status_str.strip().lower(), OrderStatus.PENDING)


def extract_status_from_detail(detail: dict) -> str:
    """Extract the best status string from a detail payload.

    Detail ``status`` is a nested object:
    ``{"current": "...", "currentType": ..., "orderStatus": "..."}``

    Precedence: ``current`` is the user-facing / order-lifecycle status
    (e.g. "Disputed Delivery Not Completed"). ``orderStatus`` is the
    financial/disbursement status (e.g. "Disbursement Complete") and must
    NOT override the lifecycle status.
    """
    status_obj = detail.get('status')
    if isinstance(status_obj, dict):
        return status_obj.get('current') or status_obj.get('orderStatus') or ''
    if isinstance(status_obj, str):
        return status_obj
    return ''


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------

PA_CATEGORY_MAP = {
    'game accounts': ProductCategory.ACCOUNTS,
    'accounts': ProductCategory.ACCOUNTS,
    'items': ProductCategory.ITEMS,
    'currency': ProductCategory.CURRENCY,
    'coins': ProductCategory.CURRENCY,
    'gold': ProductCategory.CURRENCY,
}


def map_category(product_type: str) -> str:
    """Map PlayerAuctions productType to ProductCategory."""
    if not product_type:
        return ProductCategory.ACCOUNTS
    return PA_CATEGORY_MAP.get(product_type.strip().lower(), ProductCategory.ACCOUNTS)


# ---------------------------------------------------------------------------
# Price extraction
# ---------------------------------------------------------------------------

_PRICE_RE = re.compile(r'[\$€£]?\s*([\d,]+\.?\d*)')


def parse_price_string(price_str: str) -> tuple[float, str]:
    """Parse a formatted price string like "$190.00" into (value, currency).

    Currency is inferred from the symbol prefix.
    Falls back to USD if no symbol found.
    """
    if not price_str:
        return 0.0, 'USD'

    currency = 'USD'
    if '€' in price_str:
        currency = 'EUR'
    elif '£' in price_str:
        currency = 'GBP'

    match = _PRICE_RE.search(price_str)
    if match:
        value_str = match.group(1).replace(',', '')
        try:
            return float(value_str), currency
        except ValueError:
            pass

    return 0.0, currency


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------

# PlayerAuctions datetime formats seen in the wild:
#   List endpoint:   "Mar-18-2026 10:36:48 PM"
#   Detail events:   "Mar-23-2026 12:02:16 AM(PST)"
#   Legacy:          "03/13/2025 01:11 AM"
_PA_DATETIME_FORMATS = [
    '%b-%d-%Y %I:%M:%S %p',   # Mar-18-2026 10:36:48 PM  (list createTime)
    '%m/%d/%Y %I:%M %p',      # 03/13/2025 01:11 AM      (legacy)
    '%m/%d/%Y %I:%M:%S %p',
    '%m/%d/%Y %H:%M',
    '%Y-%m-%dT%H:%M:%S',
]

# Regex to strip trailing timezone tag like "(PST)" from event log datetimes
_TZ_TAG_RE = re.compile(r'\([A-Z]{2,5}\)\s*$')


def parse_pa_datetime(dt_str: str) -> datetime | None:
    """Parse a PlayerAuctions datetime string.

    Tries multiple known formats. Returns timezone-aware UTC datetime.

    NOTE: PlayerAuctions does not specify timezone in the datetime string.
    We assume UTC for consistency. This is a known business ambiguity —
    the actual timezone may be US Pacific or the buyer's local time.
    """
    if not dt_str:
        return None

    dt_str = dt_str.strip()
    # Strip trailing timezone tag e.g. "(PST)" — we treat all as UTC
    dt_str = _TZ_TAG_RE.sub('', dt_str).strip()

    for fmt in _PA_DATETIME_FORMATS:
        try:
            dt = datetime.strptime(dt_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


# ---------------------------------------------------------------------------
# Listing reference
# ---------------------------------------------------------------------------

def extract_is_instant(detail: dict) -> bool:
    """Determine if this is an instant delivery order.

    Uses ``orderInfo.offerInfo.unit`` — value "Instant" means instant delivery.
    Falls back to False if the field is missing.
    """
    order_info = detail.get('order_info') or detail.get('orderInfo') or {}
    offer_info = order_info.get('offerInfo') or order_info.get('offer_info') or {}
    unit = offer_info.get('unit') or ''
    return unit.strip().lower() == 'instant'


def extract_login(detail: dict) -> str:
    """Extract login from PA order detail.

    Location: ``order_info.loginName``.
    """
    order_info = detail.get('order_info') or detail.get('orderInfo') or {}
    login = order_info.get('loginName') or order_info.get('login_name') or ''
    return login.strip()


def to_parsed_credentials(detail: dict):
    """Build ParsedCredentials from PA order detail.

    PA orders only provide loginName — no password field.
    Uses 'nopassworddetected' as default password.
    """
    from apps.sync.services.shared.credentials import ParsedCredentials

    login = extract_login(detail)

    return ParsedCredentials(
        login=login,
        password='nopassworddetected',
    )


# Map URL slugs from market link to PA GamePlatformMapping external_id.
# Slug is extracted from: .../LOL-account/?serverid=... -> "lol"
_SLUG_TO_PA_GAME_ID = {
    'lol': '3637',
    'valorant': '9078',
    'fortnite': '7876',
    'gta': '5917',
    'rainbow-six-siege': '7773',
    'genshin-impact': '9334',
    'cs2': '6903',
    'brawl-stars': '8463',
    'clash-royale': '7293',
    'roblox': '5204',
    'osrs': '33',
    'wow-classic': '9754',
    'wow-expansion-classic': '9754',
}


def extract_game_external_id(detail: dict) -> str:
    """Extract PA game external ID from order detail.

    PA orders don't have a direct gameId. We extract the game slug
    from the market link URL and map it to the PA GamePlatformMapping
    external_id used by ``resolve_game('playerauctions', ext_id)``.
    """
    order_info = detail.get('order_info') or detail.get('orderInfo') or {}
    market = order_info.get('market') or {}
    link = market.get('link') or ''
    if link:
        parts = link.rstrip('/').split('/')
        for part in parts:
            if '-account' in part.lower():
                slug = part.rsplit('-account', 1)[0].lower()
                return _SLUG_TO_PA_GAME_ID.get(slug, slug)
    return ''


_OFFER_ID_RE = re.compile(r'^(\d+)')


def extract_listing_id_from_detail(detail: dict) -> str:
    """Extract numeric offer/listing ID from detail orderInfo.

    Tries ``offerId`` first. If absent, extracts the numeric prefix
    from ``offerInfo.link`` slug (e.g. ``150539471a!...`` -> ``150539471``).
    """
    order_info = detail.get('order_info') or detail.get('orderInfo') or {}

    # Direct offer ID
    offer_id = order_info.get('offerId') or order_info.get('offer_id') or ''
    if offer_id:
        return str(offer_id)

    # Fallback: extract numeric prefix from offerInfo.link URL slug
    offer_info = order_info.get('offerInfo') or order_info.get('offer_info') or {}
    link = offer_info.get('link') or ''
    if link:
        # URL pattern: .../fortnite-account/150539471a!pcxblpsn--421-skins.../
        slug = link.rstrip('/').split('/')[-1]
        match = _OFFER_ID_RE.match(slug)
        if match:
            return match.group(1)

    return ''
