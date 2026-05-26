from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal

from apps.listings.enums import ListingStatus
from core.enums import ProductCategory

VariantSlugLookup = dict[str, dict[str, str]]


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------

PA_OFFER_STATUS_MAP = {
    'active': ListingStatus.LISTED,
    'hidden': ListingStatus.PAUSED,
    'expired': ListingStatus.PAUSED,
    'cancelled': ListingStatus.DELETED,
}


def map_status(status_str: str) -> str:
    """Map PA systemStatus to ListingStatus."""
    if not status_str:
        return ListingStatus.DELETED
    return PA_OFFER_STATUS_MAP.get(status_str.strip().lower(), ListingStatus.DELETED)


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------

PA_OFFER_CATEGORY_MAP = {
    'account': ProductCategory.ACCOUNTS,
    'items': ProductCategory.ITEMS,
    'currency': ProductCategory.CURRENCY,
    'coins': ProductCategory.CURRENCY,
    'gold': ProductCategory.CURRENCY,
}


def map_category(product_type: str) -> str:
    """Map PA productType to ProductCategory."""
    if not product_type:
        return ProductCategory.ACCOUNTS
    return PA_OFFER_CATEGORY_MAP.get(
        product_type.strip().lower(), ProductCategory.ACCOUNTS,
    )


# ---------------------------------------------------------------------------
# Price extraction
# ---------------------------------------------------------------------------

_PRICE_RE = re.compile(r'[\$€£]?\s*([\d,]+\.?\d*)')


def extract_price(item: dict) -> tuple[Decimal, str]:
    """Extract price from offer.

    Prefers ``details.price`` (numeric), falls back to ``totalPrice`` (string).
    """
    details = item.get('details') or {}
    price_num = details.get('price')
    if price_num is not None:
        return Decimal(str(price_num)), 'USD'

    price_str = item.get('total_price') or item.get('totalPrice') or ''
    if not price_str:
        return Decimal('0'), 'USD'

    currency = 'USD'
    if '€' in price_str:
        currency = 'EUR'
    elif '£' in price_str:
        currency = 'GBP'

    match = _PRICE_RE.search(price_str)
    if match:
        value_str = match.group(1).replace(',', '')
        try:
            return Decimal(value_str), currency
        except Exception:
            pass

    return Decimal('0'), currency


# ---------------------------------------------------------------------------
# Game extraction
# ---------------------------------------------------------------------------

def extract_game_external_id(item: dict) -> str:
    """Extract PA game ID from details.gameId."""
    details = item.get('details') or {}
    return str(details.get('gameId') or '')


# ---------------------------------------------------------------------------
# Sub-platform extraction
# ---------------------------------------------------------------------------

# Legacy fallback maps. Prefer GameVariantMapping when service passes a lookup.
_SERVER_ID_TO_PLATFORM_SLUG: dict[str, str] = {
    '9874': 'ps5',
    '9889': 'xbox-series',
    '5921': 'ps4',
    '5922': 'xbox-one',
    '14270': 'pc-enhanced',
    '14271': 'pc-enhanced',
    '14272': 'pc-enhanced',
    '5920': 'pc-legacy',
    '5919': 'pc-legacy',
    '7706': 'pc-legacy',
    # Fortnite
    '7877': 'pc',
    '7878': 'psn',
    '7879': 'xbox',
    '8173': 'android',
    '8172': 'ios',
    '8321': 'switch',
    # Rainbow Six Siege
    '7774': 'pc',
    '7775': 'psn',
    '7776': 'xbox',
}

_SERVER_ID_TO_REGION_SLUG: dict[str, str] = {
    # Valorant
    '9089': 'na',
    '9128': 'eu',
    '9207': 'la',
    '9208': 'br',
    '9309': 'ap',
    '9206': 'kr',
    '14995': 'tr',
}


def extract_variant(
    item: dict,
    slug_lookup: VariantSlugLookup | None = None,
    *,
    game_slug: str = '',
) -> str:
    """Extract canonical variant slug from details.serverId.

    PA offers store platform/server as a numeric ID in ``details.serverId``.
    Valorant has no platform dimension on PA, so we persist ``region-pc`` as
    an explicit canonical fallback.
    """
    details = item.get('details') or {}
    server_id = str(details.get('serverId') or '')

    if game_slug == 'valorant':
        region_slug = (
            _lookup_slug(slug_lookup, 'region', server_id)
            or _SERVER_ID_TO_REGION_SLUG.get(server_id, '')
        )
        return f'{region_slug}-pc' if region_slug else 'pc'

    return (
        _lookup_slug(slug_lookup, 'platform', server_id)
        or _lookup_slug(slug_lookup, 'region', server_id)
        or _SERVER_ID_TO_PLATFORM_SLUG.get(server_id, '')
    )


def _lookup_slug(
    slug_lookup: VariantSlugLookup | None,
    variant_type: str,
    external_id: str,
) -> str:
    if not external_id or not slug_lookup:
        return ''
    return (slug_lookup.get(variant_type) or {}).get(str(external_id), '')


# ---------------------------------------------------------------------------
# Delivery type
# ---------------------------------------------------------------------------

def is_instant(item: dict) -> bool:
    """Check if offer is instant delivery."""
    details = item.get('details') or {}
    if details.get('isAuto') is True:
        return True
    delivery = (
        item.get('delivery_guarantee')
        or item.get('deliveryGuarantee')
        or ''
    )
    return delivery.strip().lower() == 'instant'


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

# PA datetime formats
_PA_DATETIME_FORMATS = [
    '%b-%d-%Y %I:%M:%S %p',   # Mar-18-2026 10:36:48 PM
    '%m/%d/%Y %I:%M %p',
    '%m/%d/%Y %I:%M:%S %p',
    '%Y-%m-%dT%H:%M:%S',
]

_TZ_TAG_RE = re.compile(r'\([A-Z]{2,5}\)\s*$')


def parse_pa_datetime(dt_str: str | None) -> datetime | None:
    """Parse PA datetime string to timezone-aware datetime."""
    if not dt_str:
        return None
    dt_str = dt_str.strip()
    dt_str = _TZ_TAG_RE.sub('', dt_str).strip()
    for fmt in _PA_DATETIME_FORMATS:
        try:
            dt = datetime.strptime(dt_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Credentials helpers
# ---------------------------------------------------------------------------

def extract_login(item: dict) -> str:
    """Extract login from offer's autoDelivery credentials."""
    details = item.get('details') or {}
    auto_delivery = details.get('autoDelivery') or {}
    return str(auto_delivery.get('loginName') or '')


def to_parsed_credentials(item: dict):
    """Build ParsedCredentials from PA offer autoDelivery data."""
    from apps.sync.services.shared.credentials import ParsedCredentials

    details = item.get('details') or {}
    auto_delivery = details.get('autoDelivery') or {}

    login = str(auto_delivery.get('loginName') or '').strip()
    password = str(auto_delivery.get('password') or '').strip()
    email = str(
        (auto_delivery.get('current') or {}).get('email')
        or (auto_delivery.get('original') or {}).get('email')
        or '',
    ).strip()

    return ParsedCredentials(
        login=login,
        password=password,
        email=email if email != login else '',
    )
