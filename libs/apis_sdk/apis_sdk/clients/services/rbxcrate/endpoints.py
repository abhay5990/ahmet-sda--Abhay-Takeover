"""
RBXCrate API endpoint constants.

Centralized URL paths for the RBXCrate API.
"""


class RbxCrateEndpoints:
    """RBXCrate API endpoint paths."""

    # Stock
    STOCK = "/orders/stock"
    DETAILED_STOCK = "/orders/detailed-stock"

    # Order info / management
    ORDER_INFO = "/orders/info"
    ORDER_CANCEL = "/orders/cancel"

    # Gamepass ordering
    GAMEPASS_ORDER = "/orders/gamepass"
    GAMEPASS_RESEND = "/orders/gamepass/resend"
