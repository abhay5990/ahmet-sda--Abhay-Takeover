"""
PlayerAuctions Official Seller API endpoint constants.

All paths are relative to the base URL: https://seller-api.playerauctions.com
Endpoint reference: docs/playerauctions-offer-api.md §14.
"""


class PAOfficialEndpoints:
    """Official PA Seller API v1 endpoint paths."""

    # --- Pre-validation ---

    CREATION_PREVALIDATION = "/api/v1/offers/creation-prevalidation"
    """GET — Check seller eligibility before creating offers."""

    # --- Game metadata ---

    GAMES = "/api/v1/games"
    """GET — List all supported games."""

    @classmethod
    def game_servers(cls, game_id: int, product_type: str) -> str:
        """GET — Server/faction tree for a game + product type."""
        return f"/api/v1/games/{game_id}/{product_type}/servers"

    @classmethod
    def game_currency_types(cls, game_id: int) -> str:
        """GET — Currency types for multi-currency games."""
        return f"/api/v1/games/{game_id}/currencytypes"

    @classmethod
    def game_item_categories(cls, game_id: int) -> str:
        """GET — Item category tree for a game."""
        return f"/api/v1/games/{game_id}/items/categories"

    @classmethod
    def game_boosting_categories(cls, game_id: int) -> str:
        """GET — Boosting (powerleveling) categories for a game."""
        return f"/api/v1/games/{game_id}/powerleveling/categories"

    @classmethod
    def game_topup_categories(cls, game_id: int) -> str:
        """GET — Top-up categories for a game."""
        return f"/api/v1/games/{game_id}/topup/categories"

    @classmethod
    def game_delivery_times(cls, game_id: int, product_type: str) -> str:
        """GET — Delivery time options for a game + product type."""
        return f"/api/v1/games/{game_id}/{product_type}/deliveryTimes"

    # --- Offer CRUD (per product type) ---

    OFFER_CURRENCY = "/api/v1/offers/currency"
    """POST = create, PUT = edit."""

    OFFER_ITEM = "/api/v1/offers/item"
    """POST = create, PUT = edit."""

    OFFER_ACCOUNT = "/api/v1/offers/account"
    """POST = create, PUT = edit."""

    OFFER_POWERLEVELING = "/api/v1/offers/powerleveling"
    """POST = create, PUT = edit."""

    OFFER_TOPUP = "/api/v1/offers/topup"
    """POST = create, PUT = edit."""

    # Product type → endpoint path mapping
    OFFER_BY_TYPE: dict[str, str] = {
        "currency": OFFER_CURRENCY,
        "item": OFFER_ITEM,
        "items": OFFER_ITEM,
        "account": OFFER_ACCOUNT,
        "accounts": OFFER_ACCOUNT,
        "powerleveling": OFFER_POWERLEVELING,
        "topup": OFFER_TOPUP,
    }

    @classmethod
    def offer_by_type(cls, product_type: str) -> str:
        """Resolve the offer endpoint path for a product type."""
        path = cls.OFFER_BY_TYPE.get(product_type.lower())
        if path is None:
            raise ValueError(f"Unknown product type: {product_type!r}")
        return path

    @classmethod
    def offer_detail(cls, product_type: str, offer_id: int) -> str:
        """GET — Query a single offer by type and ID."""
        base = cls.offer_by_type(product_type)
        return f"{base}/{offer_id}"

    # --- Offer management ---

    LIST_OFFERS = "/api/v1/offers"
    """GET — Paginated list of seller offers."""

    CANCELLATION_ELIGIBILITY = "/api/v1/offers/cancellation-eligibility"
    """POST — Check if offers can be cancelled."""

    DISPLAY_STATUS = "/api/v1/offers/display-status"
    """POST — Hide or show offers."""

    CANCEL_OFFERS = "/api/v1/offers/cancel"
    """POST — Permanently cancel offers."""

    # --- Bulk operations ---

    BULK_TEMPLATE = "/api/v1/offers/bulk-template"
    """GET — Download bulk upload template (.xlsx)."""

    BULK_UPLOAD = "/api/v1/offers/bulk-upload"
    """POST — Upload filled bulk template (multipart/form-data)."""

    BULK_UPLOAD_QUERY = "/api/v1/offers/bulk-upload"
    """GET — Query results of prior bulk uploads."""

    # --- Media / Images ---

    MEDIA_IMAGES = "/api/v1/media/images"
    """POST = upload (multipart), GET = query gallery, DELETE = delete."""
