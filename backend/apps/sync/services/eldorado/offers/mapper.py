from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from apps.listings.enums import ListingStatus
from apps.sync.services.shared.credentials import ParsedCredentials, parse_credentials_text
from core.enums import ProductCategory


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
        offer_state.lower(), ListingStatus.CLOSED,
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
# Sub-platform extraction
# ---------------------------------------------------------------------------

def extract_sub_platform(item: dict) -> str:
    """Extract sub-platform from tradeEnvironmentValues.

    Eldorado API returns::

        "tradeEnvironmentValues": [
            {"id": "0", "name": "Device", "value": "PC", "imageLocation": null}
        ]

    The ``value`` field gives the human-readable platform name (PC, PlayStation,
    Xbox, iOS, Android, Switch).  Returns empty string when not present.
    """
    trade_envs = item.get('tradeEnvironmentValues') or []
    if not trade_envs:
        return ''
    return (trade_envs[0].get('value') or '').strip()


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
