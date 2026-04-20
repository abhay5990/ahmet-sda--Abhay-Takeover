"""
LZT Market API endpoint constants.

Centralized URL paths for the LZT Market API.
"""


class LztEndpoints:
    """LZT Market API endpoint paths."""

    # User endpoints
    USER_ORDERS = "/user/orders"
    USER_ITEMS = "/user/items"

    # Mail access (email:password validation + inbox)
    LETTERS2 = "/letters2"

    # Category listings (dynamic)
    @classmethod
    def category(cls, category: str) -> str:
        """Category listing endpoint (e.g. /steam, /roblox, /supercell)."""
        return f"/{category}"

    @classmethod
    def item(cls, item_id: str) -> str:
        """Single item details endpoint."""
        return f"/{item_id}"

    # Purchase flow
    @classmethod
    def check_account(cls, item_id: str) -> str:
        """Pre-purchase availability check endpoint."""
        return f"/{item_id}/check-account"

    @classmethod
    def confirm_buy(cls, item_id: str) -> str:
        """Purchase confirmation endpoint."""
        return f"/{item_id}/confirm-buy"
