"""
PlayerAuctions API endpoint constants.

Centralized URL paths for the PlayerAuctions marketplace API.
All currently known endpoints are listed here, even if not all
are implemented yet. Unimplemented operations are marked.

PlayerAuctions uses two base URLs:
- offer_base_url: offers, games
- order_base_url: orders
"""


class PlayerAuctionsEndpoints:
    """PlayerAuctions API endpoint paths."""

    # --- Offer endpoints (offer_base_url) ---

    CREATE_OFFER = "/api/offers/account"
    """POST — Create a single offer."""

    LIST_OFFERS = "/api/Offer/Offers"
    """GET — List seller offers with pagination."""

    CANCEL_OFFERS = "/api/Offer/Cancel"
    """POST — Cancel/delete offers by IDs."""

    BULK_UPLOAD = "/api/Offer/bulkOfferUpload"
    """POST — Bulk upload offers from Excel file."""

    # --- Order endpoints (order_base_url) ---

    LIST_SELLER_ORDERS = "/api/Order/SellerOrders"
    """GET — List seller orders with filters and pagination."""

    # --- Parameterized paths ---

    @classmethod
    def offer_details(cls, offer_id: str) -> str:
        """GET — Fetch a specific offer by ID."""
        return f"/api/offers/Account/{offer_id}"

    @classmethod
    def order_details(cls, order_id: str) -> str:
        """GET — Fetch order details."""
        return f"/api/orderdetail/{order_id}"

    @classmethod
    def game_account_servers(cls, game_id: int) -> str:
        """GET — Fetch server options for a game."""
        return f"/api/games/{game_id}/account/servers"
