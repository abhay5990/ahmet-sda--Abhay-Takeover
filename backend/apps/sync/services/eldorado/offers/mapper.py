from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal

from apps.listings.enums import ListingStatus
from apps.sync.services.shared.credentials import ParsedCredentials, parse_credentials_text
from core.enums import ProductCategory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------

ELDORADO_OFFER_STATUS_MAP = {
    'active': ListingStatus.LISTED,
    'paused': ListingStatus.PAUSED,
}


def map_status(offer_state: str) -> str:
    """Map Eldorado offerState to ListingStatus."""
    return ELDORADO_OFFER_STATUS_MAP.get(
        offer_state.lower(), ListingStatus.DELETED,
    )


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------

ELDORADO_CATEGORY_MAP = {
    'Account': ProductCategory.ACCOUNTS,
    'Currency': ProductCategory.CURRENCY,
    'CustomItem': ProductCategory.ITEMS,
    'GiftCard': ProductCategory.GIFT_CARD,
    'TopUp': ProductCategory.TOP_UP,
}


def map_category(category: str | None) -> str:
    """Map Eldorado category string to ProductCategory."""
    return ELDORADO_CATEGORY_MAP.get(category, ProductCategory.ITEMS)


# ---------------------------------------------------------------------------
# Price extraction
# ---------------------------------------------------------------------------

def extract_price(item: dict) -> tuple[Decimal, str]:
    """Extract price from flat offer structure.

    Returns (amount, currency).
    """
    price = item.get('pricePerUnit') or {}
    amount = price.get('amount', 0)
    currency = price.get('currency', 'USD')
    return Decimal(str(amount)), currency


# ---------------------------------------------------------------------------
# Game extraction
# ---------------------------------------------------------------------------

def extract_game_external_id(item: dict) -> str:
    """Extract Eldorado game ID (root-level flat field)."""
    return str(item.get('gameId') or '')


# ---------------------------------------------------------------------------
# Delivery type
# ---------------------------------------------------------------------------

def is_instant(item: dict) -> bool:
    """Check if offer is instant delivery."""
    return item.get('guaranteedDeliveryTime') == 'Instant'


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------

def parse_iso_timestamp(ts: str | None) -> datetime | None:
    """Parse ISO 8601 timestamp string to timezone-aware datetime."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        # Ensure timezone-aware (Eldorado sometimes omits tz info)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Variant extraction
# ---------------------------------------------------------------------------

_DIMENSION_TYPE_MAP = {
    'device': 'platform',
    'platform': 'platform',
    'region': 'region',
    'server': 'region',
}

_VALUE_SLUG_MAP = {
    # Platforms
    'pc': 'pc',
    'playstation': 'psn',
    'psn': 'psn',
    'xbox': 'xbox',
    'ios': 'ios',
    'android': 'android',
    'switch': 'switch',
    'nintendo switch': 'switch',
    # Valorant regions
    'na': 'na',
    'eu': 'eu',
    'eu/tr/mena/cis': 'eu',
    'ap': 'ap',
    'apac': 'ap',
    'brazil': 'br',
    'br': 'br',
    'latam': 'la',
    'la': 'la',
    'korea': 'kr',
    'kr': 'kr',
    'turkey': 'tr',
    'tr': 'tr',
}

VariantSlugLookup = dict[str, dict[str, str]]


def extract_variant(
    item: dict,
    slug_lookup: VariantSlugLookup | None = None,
    *,
    game_slug: str = '',
) -> str:
    """Extract a canonical composite variant slug from tradeEnvironmentValues.

    Eldorado API returns::

        "tradeEnvironmentValues": [
            {"id": "0", "name": "Device", "value": "PC", "imageLocation": null}
        ]

    Multi-dimensional games return cumulative IDs, e.g. Valorant AP + PC:
    ``Region`` id ``5`` followed by ``Device`` id ``5-0``. The lookup is
    keyed by dimension type so region id ``1`` cannot collide with platform
    id ``1``.
    """
    trade_envs = item.get('tradeEnvironmentValues') or []
    if not trade_envs:
        return ''

    slugs: list[str] = []
    for index, entry in enumerate(trade_envs):
        slug = _resolve_trade_env_slug(
            entry,
            index=index,
            slug_lookup=slug_lookup,
            game_slug=game_slug,
        )
        if slug:
            slugs.append(slug)

    return '-'.join(slugs)


def _resolve_trade_env_slug(
    entry: dict,
    *,
    index: int,
    slug_lookup: VariantSlugLookup | None,
    game_slug: str,
) -> str:
    variant_type = _dimension_to_variant_type(entry.get('name'))
    candidates = _external_id_candidates(entry.get('id'), index)

    if slug_lookup and variant_type:
        type_lookup = slug_lookup.get(variant_type) or {}
        for candidate in candidates:
            slug = type_lookup.get(candidate)
            if slug:
                return slug

    value = (entry.get('value') or '').strip()
    slug, known = _normalize_eldorado_value(value)
    if value and not known:
        logger.warning(
            "Unknown Eldorado tradeEnvironment value: game=%s dimension=%s "
            "id=%s value=%s normalized=%s",
            game_slug or 'unknown',
            entry.get('name') or '',
            entry.get('id') or '',
            value,
            slug,
        )
    return slug


def _dimension_to_variant_type(name: str | None) -> str:
    return _DIMENSION_TYPE_MAP.get(str(name or '').strip().lower(), '')


def _external_id_candidates(raw_id: object, index: int) -> list[str]:
    raw = str(raw_id or '').strip()
    if not raw:
        return []

    candidates = [raw]
    parts = [part for part in raw.split('-') if part != '']
    if len(parts) > index:
        candidates.append(parts[index])
    if parts:
        candidates.append(parts[-1])

    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _normalize_eldorado_value(value: str) -> tuple[str, bool]:
    key = value.strip().lower()
    if key in _VALUE_SLUG_MAP:
        return _VALUE_SLUG_MAP[key], True

    slug = re.sub(r'[^a-z0-9]+', '-', key).strip('-')
    return slug, False


# ---------------------------------------------------------------------------
# Credentials helpers
# ---------------------------------------------------------------------------


def parse_credentials_from_secret_details(secret_details: str) -> ParsedCredentials:
    """Parse full credentials from Eldorado secretDetails string.

    Delegates to the shared credential parser which handles arrow format
    (``Key -> Value``), labeled lines, colon-separated, etc.
    """
    if not secret_details:
        return ParsedCredentials()
    return parse_credentials_text(secret_details)


def parse_credentials_from_credential_entries(
    credential_entries: list[dict],
) -> list[ParsedCredentials]:
    """Parse full credentials from credential API response entries.

    Each entry has a ``secretDetails`` string field.
    Returns list of ParsedCredentials (one per entry with non-empty login).
    """
    results: list[ParsedCredentials] = []
    for entry in credential_entries:
        secret = entry.get('secretDetails', '')
        if not secret:
            continue
        parsed = parse_credentials_text(secret)
        if parsed.login:
            results.append(parsed)
    return results


def extract_logins_from_credential_entries(
    credential_entries: list[dict],
) -> list[str]:
    """Extract logins from credential entries (backward-compatible wrapper)."""
    return [
        p.login for p in parse_credentials_from_credential_entries(credential_entries)
    ]
