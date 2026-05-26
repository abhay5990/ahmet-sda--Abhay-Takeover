from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from apps.listings.enums import ListingStatus
from core.enums import ProductCategory

VariantSlugLookup = dict[str, dict[str, str]]

_PLATFORM_SLUG_MAP = {
    'pc': 'pc',
    'playstation': 'psn',
    'psn': 'psn',
    'xbox': 'xbox',
}

_REGION_SLUG_MAP = {
    'north america': 'na',
    'europe': 'eu',
    'latin america': 'la',
    'brazil': 'br',
    'asia pacific': 'ap',
    'korea': 'kr',
}


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------

GAMEBOOST_OFFER_STATUS_MAP = {
    'listed': ListingStatus.LISTED,
    'draft': ListingStatus.PAUSED,
}


def map_status(status_str: str) -> str:
    """Map Gameboost offer status string to ListingStatus."""
    return GAMEBOOST_OFFER_STATUS_MAP.get(
        status_str.lower(), ListingStatus.DELETED,
    )


# ---------------------------------------------------------------------------
# Price extraction
# ---------------------------------------------------------------------------

def extract_price(item: dict) -> tuple[Decimal, str]:
    """Extract canonical price from the offer.

    Prefers ``price_usd.value``, falls back to ``price.value`` (EUR).
    Returns (price_value, currency_code).
    """
    price_usd = item.get('price_usd')
    if isinstance(price_usd, dict) and price_usd.get('value') is not None:
        return Decimal(str(price_usd['value'])), 'USD'

    price_obj = item.get('price')
    if isinstance(price_obj, dict) and price_obj.get('value') is not None:
        currency = 'EUR'
        cur = price_obj.get('currency')
        if isinstance(cur, dict) and cur.get('code'):
            currency = cur['code']
        return Decimal(str(price_obj['value'])), currency

    return Decimal('0'), 'USD'


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def parse_unix_timestamp(ts: int | None) -> datetime | None:
    """Convert a unix epoch integer to a timezone-aware datetime."""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


# ---------------------------------------------------------------------------
# Game extraction
# ---------------------------------------------------------------------------

def extract_game_external_id(item: dict) -> str:
    """Extract the Gameboost game ID from the offer."""
    game = item.get('game') or {}
    return str(game.get('id') or '')


def extract_variant(
    item: dict,
    slug_lookup: VariantSlugLookup | None = None,
    *,
    game_slug: str = '',
) -> str:
    """Extract canonical variant slug from GameBoost parameters.

    Gameboost offers include platform info in ``parameters``::

        "parameters": {"platform": "PlayStation 5", ...}

    Valorant carries region in ``parameters.server`` and platforms in
    ``parameters.platforms``. For that game we persist ``region-platform``
    to match the canonical Listing.variant format used across marketplaces.
    """
    params = item.get('parameters') or {}

    if game_slug == 'valorant':
        region_slug = (
            _lookup_slug(slug_lookup, 'region', params.get('server'))
            or _normalize_region(params.get('server'))
        )
        platform_slug = (
            _lookup_slug(slug_lookup, 'platform', _first_platform(params))
            or _normalize_platform(_first_platform(params))
            or 'pc'
        )
        if region_slug:
            return f'{region_slug}-{platform_slug}'
        return platform_slug

    platform = params.get('platform') or _first_platform(params)
    return (
        _lookup_slug(slug_lookup, 'platform', platform)
        or _normalize_platform(platform)
    )


def _first_platform(params: dict) -> str:
    platforms = params.get('platforms')
    if isinstance(platforms, list) and platforms:
        return str(platforms[0] or '').strip()
    return str(params.get('platform') or '').strip()


def _lookup_slug(
    slug_lookup: VariantSlugLookup | None,
    variant_type: str,
    external_value: object,
) -> str:
    value = str(external_value or '').strip()
    if not value or not slug_lookup:
        return ''
    return (slug_lookup.get(variant_type) or {}).get(value, '')


def _normalize_platform(value: object) -> str:
    key = str(value or '').strip().lower()
    return _PLATFORM_SLUG_MAP.get(key, '')


def _normalize_region(value: object) -> str:
    key = str(value or '').strip().lower()
    return _REGION_SLUG_MAP.get(key, '')


# ---------------------------------------------------------------------------
# Credentials helpers
# ---------------------------------------------------------------------------

def is_legacy_offer(item: dict) -> bool:
    """Legacy offers have credentials inline (credentials.login is not None)."""
    creds = item.get('credentials') or {}
    return creds.get('login') is not None


def extract_login_from_inline(item: dict) -> str:
    """Extract login from legacy offer's inline credentials."""
    creds = item.get('credentials') or {}
    return str(creds.get('login') or '')


def parse_credentials_from_legacy(item: dict):
    """Build ParsedCredentials from legacy inline structured credentials.

    Legacy offers store credentials as a dict with structured fields:
        login, password, email_login, email_password, email_provider
    """
    from apps.sync.services.shared.credentials import ParsedCredentials

    creds = item.get('credentials') or {}
    login = str(creds.get('login') or '')
    password = str(creds.get('password') or '')
    email = str(creds.get('email_login') or '')
    email_password = str(creds.get('email_password') or '')

    return ParsedCredentials(
        login=login,
        password=password,
        email=email,
        email_password=email_password,
    )


def parse_credentials_from_delivery_instructions(item: dict):
    """Parse credentials from delivery_instructions field (last resort).

    Some offers store credential info in delivery_instructions as free text.
    """
    from apps.sync.services.shared.credentials import ParsedCredentials, parse_credentials_text

    text = item.get('delivery_instructions', '')
    if not text:
        return ParsedCredentials()
    return parse_credentials_text(text)


def parse_credentials_from_entries(
    credential_entries: list[dict],
):
    """Parse full credentials from credential API response entries.

    Each entry has a ``credentials`` string field.
    Returns list of ParsedCredentials (one per entry with non-empty login).
    """
    from apps.sync.services.shared.credentials import ParsedCredentials, parse_credentials_text

    results: list[ParsedCredentials] = []
    for entry in credential_entries:
        cred_str = entry.get('credentials', '')
        if not cred_str:
            continue
        parsed = parse_credentials_text(cred_str)
        if parsed.login:
            results.append(parsed)
    return results


def extract_login_from_credential_entries(
    credential_entries: list[dict],
) -> list[str]:
    """Extract logins from credential entries (backward-compatible wrapper)."""
    return [p.login for p in parse_credentials_from_entries(credential_entries)]
