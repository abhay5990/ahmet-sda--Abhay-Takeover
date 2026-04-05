from __future__ import annotations

from apps.orders.enums import OrderStatus
from apps.sync.services.shared.credentials import ParsedCredentials, parse_credentials_text
from core.enums import ProductCategory

ELDORADO_STATUS_MAP = {
    'Initialized': OrderStatus.PENDING,
    'PendingReview': OrderStatus.PENDING,
    'Paid': OrderStatus.PENDING,
    'Delivered': OrderStatus.DELIVERED,
    'Received': OrderStatus.DELIVERED,
    'Completed': OrderStatus.COMPLETED,
    'Canceled': OrderStatus.CANCELLED,
    'Refunded': OrderStatus.REFUNDED,
    'Disputed': OrderStatus.DISPUTED,
    'DeliveredDisputed': OrderStatus.DISPUTED,
}


def map_status(payload: dict) -> str:
    """Map Eldorado order payload to OrderStatus.

    Uses only ``state.state`` for mapping. The ``dispute`` object
    retains historical dispute info even after resolution, so it
    must NOT be used to determine current status.
    ``DeliveredDisputed`` state already maps to DISPUTED for
    genuinely active disputes.
    """
    state = (payload.get('state') or {}).get('state', '')
    return ELDORADO_STATUS_MAP.get(state, OrderStatus.PENDING)


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


def extract_game_external_id(payload: dict) -> str:
    """Extract Eldorado game ID from order payload."""
    offer = payload.get('orderOfferDetails') or {}
    return str(offer.get('gameId') or '')


def parse_credentials_from_account_details(payload: dict) -> ParsedCredentials:
    """Parse full credentials from enriched accountDetails.secretDetails.

    Delegates to the shared credential parser which handles arrow format,
    labeled lines, colon-separated, and other formats.
    """
    ad = payload.get('accountDetails') or {}
    secret = ad.get('secretDetails', '')
    if not secret:
        return ParsedCredentials()
    return parse_credentials_text(secret)


def extract_login_from_account_details(payload: dict) -> str:
    """Extract login from accountDetails.secretDetails.

    Thin wrapper around parse_credentials_from_account_details for
    backward compatibility.
    """
    return parse_credentials_from_account_details(payload).login


_SKIP_ENRICHMENT_STATES = {'Canceled', 'Refunded'}


def needs_enrichment(item: dict) -> bool:
    """Check if this order needs account details enrichment.

    Predicate: category == "Account" AND guaranteedDeliveryTime == "Instant"
    AND order is not canceled/refunded (account details won't exist).
    """
    state = (item.get('state') or {}).get('state', '')
    if state in _SKIP_ENRICHMENT_STATES:
        return False

    offer = item.get('orderOfferDetails') or {}
    return (
        offer.get('category') == 'Account'
        and offer.get('guaranteedDeliveryTime') == 'Instant'
    )
