from __future__ import annotations

from datetime import datetime, timezone

from apps.orders.enums import OrderStatus
from core.enums import ProductCategory

# ---------------------------------------------------------------------------
# Status mapping
# ---------------------------------------------------------------------------

GAMEBOOST_STATUS_MAP = {
    'new': OrderStatus.PENDING,
    'in_delivery': OrderStatus.PENDING,
    'delivered': OrderStatus.DELIVERED,
    'completed': OrderStatus.COMPLETED,
    'refunded': OrderStatus.REFUNDED,
    'cancelled': OrderStatus.CANCELLED,
    'disputed': OrderStatus.DISPUTED,
}


def map_status(status_str: str) -> str:
    """Map Gameboost order status string to OrderStatus."""
    return GAMEBOOST_STATUS_MAP.get(status_str.lower(), OrderStatus.PENDING)


# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------

def map_category(item: dict) -> str:
    """Determine product category from order shape.

    Account orders have ``account_offer_id``.
    Currency orders have ``currency_offer_id``.
    """
    if item.get('currency_offer_id'):
        return ProductCategory.CURRENCY
    return ProductCategory.ACCOUNTS


# ---------------------------------------------------------------------------
# Price extraction
# ---------------------------------------------------------------------------

def extract_price_usd(item: dict) -> tuple[float, str]:
    """Extract canonical price in USD from the order.

    Decision: We use ``price_usd.value`` as the canonical price.
    For currency orders, ``price_usd`` may also be present; if not,
    fall back to ``price_eur.value`` with EUR currency.

    Returns (price_value, currency_code).
    """
    price_usd = item.get('price_usd')
    if isinstance(price_usd, dict) and price_usd.get('value') is not None:
        return float(price_usd['value']), 'USD'

    # Fallback: account order ``price`` field (typically EUR)
    price_obj = item.get('price')
    if isinstance(price_obj, dict) and price_obj.get('value') is not None:
        currency = 'EUR'
        cur = price_obj.get('currency')
        if isinstance(cur, dict) and cur.get('code'):
            currency = cur['code']
        return float(price_obj['value']), currency

    # Currency order fallback: price_eur
    price_eur = item.get('price_eur')
    if isinstance(price_eur, dict) and price_eur.get('value') is not None:
        return float(price_eur['value']), 'EUR'

    return 0.0, 'USD'


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
# Listing reference
# ---------------------------------------------------------------------------

def extract_listing_id(item: dict) -> str:
    """Extract the store listing ID from the order."""
    offer_id = item.get('account_offer_id') or item.get('currency_offer_id')
    return str(offer_id) if offer_id else ''


# ---------------------------------------------------------------------------
# Game & login extraction (for OwnedProduct matching)
# ---------------------------------------------------------------------------

def extract_game_external_id(item: dict) -> str:
    """Extract the Gameboost game ID from the order."""
    game = item.get('game') or {}
    return str(game.get('id') or '')


def parse_credentials_from_inline(item: dict):
    """Parse full credentials from inline credentials string.

    Returns ParsedCredentials with all extracted fields.
    """
    from apps.sync.services.shared.credentials import ParsedCredentials, parse_credentials_text

    creds = item.get('credentials', '')
    if not creds:
        return ParsedCredentials()
    return parse_credentials_text(creds)


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


def parse_credentials_from_delivery_instructions(item: dict):
    """Parse credentials from delivery_instructions field (last resort)."""
    from apps.sync.services.shared.credentials import ParsedCredentials, parse_credentials_text

    text = item.get('delivery_instructions', '')
    if not text:
        return ParsedCredentials()
    return parse_credentials_text(text)


def extract_login_from_credentials(item: dict) -> str:
    """Extract login from inline credentials (backward-compatible wrapper)."""
    return parse_credentials_from_inline(item).login


def extract_login_from_credential_entries(
    credential_entries: list[dict],
) -> list[str]:
    """Extract logins from credential entries (backward-compatible wrapper)."""
    return [p.login for p in parse_credentials_from_entries(credential_entries)]
