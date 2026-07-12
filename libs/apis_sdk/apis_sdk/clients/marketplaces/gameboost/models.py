"""
GameBoost API response models.

These represent the raw API contract with GameBoost.
Models use permissive defaults so that missing fields don't
cause parse failures — the API may return partial data.

Two order types exist:
- Account orders (standard): price/price_usd are nested objects
- Currency orders: have quantity, currency_unit, price_eur/price_usd,
  unit_price_eur/unit_price_usd instead

Both share common fields (id, game, buyer, status, timestamps, etc.)
and are modeled with a single permissive GameBoostOrder.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Price sub-models
# ---------------------------------------------------------------------------

class GameBoostCurrency(BaseModel):
    """Currency info nested inside price objects."""

    symbol: str = ""
    code: str = ""


class GameBoostPrice(BaseModel):
    """Price object as returned by GameBoost responses.

    Covers both ``price`` and ``price_usd`` shapes for account orders/offers,
    and ``price_eur``/``price_usd`` for currency orders.
    """

    format: str = ""
    value: float = 0.0
    amount: int | float = 0
    currency: GameBoostCurrency = Field(default_factory=GameBoostCurrency)


class GameBoostUnitPrice(BaseModel):
    """Unit price object for currency orders (unit_price_eur / unit_price_usd)."""

    format: str = ""
    format_readable: str = ""
    amount: float = 0.0
    currency: str = ""


# ---------------------------------------------------------------------------
# Delivery time
# ---------------------------------------------------------------------------

class GameBoostDeliveryTime(BaseModel):
    """Delivery time object from order/offer responses."""

    format: str = ""
    formatLong: str = Field(default="", alias="formatLong")
    seconds: int = 0
    duration: int = 0
    unit: str = ""

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Game / Buyer sub-models
# ---------------------------------------------------------------------------

class GameBoostGame(BaseModel):
    """Game info nested inside order/offer responses."""

    id: int = 0
    name: str = ""
    slug: str = ""
    acronym: str = ""


class GameBoostBuyer(BaseModel):
    """Buyer info nested inside order responses."""

    id: int = 0
    username: str = ""


# ---------------------------------------------------------------------------
# Currency unit (currency orders only)
# ---------------------------------------------------------------------------

class GameBoostCurrencyUnit(BaseModel):
    """Currency unit info for currency orders (e.g. Robux)."""

    slug: str = ""
    currency_name: str = ""
    name: str = ""
    symbol: str = ""
    multiplier: int | float = 1


# ---------------------------------------------------------------------------
# Offer credentials sub-models
# ---------------------------------------------------------------------------

class GameBoostOfferCredentials(BaseModel):
    """Credentials embedded in an offer response (null when not owned)."""

    login: str | None = None
    password: str | None = None
    email_login: str | None = None
    email_password: str | None = None
    email_provider: str | None = None


class GameBoostCredentialEntry(BaseModel):
    """A single credential record from the /account-offers/{id}/credentials endpoint."""

    id: int = 0
    credentials: str = ""
    account_offer_id: int = 0
    account_order_id: int | None = None
    is_sold: bool = False
    created_at: int | None = None
    updated_at: int | None = None


class GameBoostAddCredentialsResponse(BaseModel):
    """Response from POST /account-offers/{id}/credentials (add credentials)."""

    message: str = ""
    created_count: int = 0
    duplicate_count: int = 0
    data: list[GameBoostCredentialEntry] = Field(default_factory=list)


class GameBoostBulkDeleteCredentialsResponse(BaseModel):
    """Response from POST /account-offers/{id}/credentials/bulk-delete."""

    message: str = ""
    deleted_count: int = 0


# ---------------------------------------------------------------------------
# Account Offer action / template models
# ---------------------------------------------------------------------------

class GameBoostAccountOfferActionResponse(BaseModel):
    """Response from list/unlist/duplicate account offer actions.

    These POST endpoints return the offer data plus action metadata.
    """

    data: dict[str, Any] = Field(default_factory=dict)  # raw offer dict (reuses GameBoostOffer shape)
    message: str = ""
    action: str = ""
    previous_status: str = ""


class GameBoostAccountOfferTemplate(BaseModel):
    """Template for creating an account offer for a specific game."""

    game: str = ""
    title: str = ""
    slug: str = ""
    price: float = 0.0
    login: str = ""
    password: str = ""
    email_login: str = ""
    email_password: str = ""
    is_manual: str = ""
    delivery_time: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    dump: str = ""
    delivery_instructions: str = ""
    image_urls: list[str] = Field(default_factory=list)
    account_data: dict[str, Any] = Field(default_factory=dict)
    game_items: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Order message models
# ---------------------------------------------------------------------------

class GameBoostMessageSender(BaseModel):
    """Sender info nested inside message responses."""

    id: int = 0
    username: str = ""
    is_admin: bool | None = None


class GameBoostMessage(BaseModel):
    """A single message from an account order message thread."""

    id: str = ""
    type: str = ""
    text: str = ""
    attachment: Any = None
    sender: GameBoostMessageSender = Field(default_factory=GameBoostMessageSender)
    sent_at: int | None = None


# ---------------------------------------------------------------------------
# Offer model
# ---------------------------------------------------------------------------

class GameBoostOffer(BaseModel):
    """An account offer as returned by the GameBoost API.

    Covers both list and detail responses. All fields use permissive
    defaults so that missing or partial data does not cause parse failures.
    """

    id: int = 0
    external_id: str | None = None
    game: GameBoostGame = Field(default_factory=GameBoostGame)
    account_order_ids: list[int] = Field(default_factory=list)

    title: str = ""
    slug: str = ""
    description: str = ""
    parameters: dict[str, Any] | list[Any] = Field(default_factory=dict)
    dump: str | None = None

    status: str = ""
    delivery_time: GameBoostDeliveryTime = Field(default_factory=GameBoostDeliveryTime)
    is_manual_delivery: bool = False

    credentials: GameBoostOfferCredentials | None = None
    delivery_instructions: str | None = None

    price: GameBoostPrice | None = None
    price_usd: GameBoostPrice | None = None

    views: int = 0
    image_urls: list[str] = Field(default_factory=list)

    # Timestamps (unix epoch integers)
    created_at: int | None = None
    updated_at: int | None = None
    listed_at: int | None = None

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Order model — covers both account orders and currency orders
# ---------------------------------------------------------------------------

class GameBoostOrder(BaseModel):
    """An order as returned by the GameBoost API.

    Unified model covering both account orders and currency orders.
    Account orders use: id, account_offer_id, price, price_usd
    Currency orders use: id, currency_offer_id, quantity, currency_unit,
                         price_eur, price_usd, unit_price_eur, unit_price_usd

    All fields are optional/defaulted so neither variant causes parse failures.
    """

    id: int = 0
    # Account order link
    account_offer_id: int | None = None
    # Currency order link
    currency_offer_id: int | None = None

    game: GameBoostGame = Field(default_factory=GameBoostGame)
    buyer: GameBoostBuyer = Field(default_factory=GameBoostBuyer)
    rating: Any = None
    title: str = ""
    description: str = ""
    parameters: dict[str, Any] | list[Any] = Field(default_factory=dict)
    status: str = ""

    delivery_time: GameBoostDeliveryTime = Field(default_factory=GameBoostDeliveryTime)
    is_manual_delivery: bool = False

    credentials: Any = None  # str for account orders, dict for currency orders
    delivery_instructions: str | None = ""

    # Account order price fields
    price: GameBoostPrice | None = None
    price_usd: GameBoostPrice | None = None

    # Currency order price fields
    price_eur: GameBoostPrice | None = None
    unit_price_eur: GameBoostUnitPrice | None = None
    unit_price_usd: GameBoostUnitPrice | None = None

    # Currency order quantity
    quantity: int | None = None
    currency_unit: GameBoostCurrencyUnit | None = None

    image_urls: list[str] = Field(default_factory=list)

    # Timestamps (unix epoch integers)
    created_at: int | None = None
    updated_at: int | None = None
    purchased_at: int | None = None
    completed_at: int | None = None
    refunded_at: int | None = None

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Item Offer model
# ---------------------------------------------------------------------------

class GameBoostItemOffer(BaseModel):
    """An item offer as returned by the GameBoost API.

    Unlike account offers, item offers use string prices (not nested objects)
    and have stock/min_quantity instead of credentials.
    """

    id: int = 0
    external_id: str | None = None
    game: GameBoostGame = Field(default_factory=GameBoostGame)

    title: str = ""
    slug: str = ""
    description: str = ""
    parameters: dict[str, Any] | list[Any] | None = None

    status: str = ""
    delivery_time: GameBoostDeliveryTime = Field(default_factory=GameBoostDeliveryTime)
    delivery_instructions: str | None = None

    stock: int = 0
    min_quantity: int = 1

    # Prices can be plain strings OR nested objects (API returns objects)
    price_eur: str | dict | None = None
    price_usd: str | dict | None = None

    views: int = 0
    image_urls: list[str] = Field(default_factory=list)

    created_at: int | None = None
    updated_at: int | None = None
    listed_at: int | None = None

    model_config = {"populate_by_name": True}


class GameBoostItemOfferActionResponse(BaseModel):
    """Response from list/unlist/archive item offer actions.

    These POST endpoints return the offer data plus action metadata.
    """

    data: GameBoostItemOffer = Field(default_factory=GameBoostItemOffer)
    message: str = ""
    action: str = ""
    previous_status: str = ""


class GameBoostItemOfferTemplate(BaseModel):
    """Template for creating an item offer for a specific game."""

    game: str = ""
    title: str = ""
    slug: str = ""
    description: str = ""
    price: float = 0.0
    stock: int = 0
    min_quantity: int = 1
    delivery_time: dict[str, Any] = Field(default_factory=dict)
    delivery_instructions: str = ""
    image_urls: list[str] = Field(default_factory=list)
    item_data: Any = None


# ---------------------------------------------------------------------------
# Item Order model
# ---------------------------------------------------------------------------

class GameBoostItemOrder(BaseModel):
    """An item order as returned by the GameBoost API.

    Item orders have quantity, string prices, and unit prices.
    No credentials field — items are delivered differently from accounts.
    """

    id: int = 0
    item_offer_id: int | None = None

    game: GameBoostGame = Field(default_factory=GameBoostGame)
    buyer: GameBoostBuyer = Field(default_factory=GameBoostBuyer)
    rating: Any = None
    title: str = ""
    description: str = ""
    quantity: int = 0
    parameters: dict[str, Any] | list[Any] = Field(default_factory=dict)
    status: str = ""

    delivery_time: GameBoostDeliveryTime = Field(default_factory=GameBoostDeliveryTime)

    # Prices are plain strings for item orders
    price_eur: str | dict | None = ""
    price_usd: str | dict | None = ""
    unit_price_eur: str | dict | None = ""
    unit_price_usd: str | dict | None = ""

    created_at: int | None = None
    updated_at: int | None = None
    purchased_at: int | None = None
    completed_at: int | None = None
    refunded_at: int | None = None

    model_config = {"populate_by_name": True}


class GameBoostItemOrderActionResponse(BaseModel):
    """Response from complete item order action."""

    data: GameBoostItemOrder = Field(default_factory=GameBoostItemOrder)
    message: str = ""
    action: str = ""


# ---------------------------------------------------------------------------
# Gift Card Catalog sub-models
# ---------------------------------------------------------------------------

class GameBoostGiftCardRegion(BaseModel):
    """Region info for gift cards."""

    id: int = 0
    code: str = ""
    name: str = ""
    slug: str = ""
    is_country: bool = False


class GameBoostGiftCardBrand(BaseModel):
    """Brand info for gift cards."""

    id: int = 0
    name: str = ""
    slug: str = ""


class GameBoostGiftCard(BaseModel):
    """A gift card catalog entry.

    Represents a specific denomination/region combination (e.g. $50 Steam US).
    """

    id: int = 0
    region_id: int = 0
    brand_id: int = 0
    region: GameBoostGiftCardRegion = Field(default_factory=GameBoostGiftCardRegion)
    brand: GameBoostGiftCardBrand = Field(default_factory=GameBoostGiftCardBrand)
    title: str = ""
    face_value_amount: str = ""
    face_value_unit: str | None = None
    face_value_unit_slug: str | None = None
    lowest_price_eur: str | None = None
    lowest_price_usd: str | None = None
    highest_price_eur: str | None = None
    highest_price_usd: str | None = None
    is_enabled: bool = True
    created_at: int | None = None
    updated_at: int | None = None

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Gift Card Offer model
# ---------------------------------------------------------------------------

class GameBoostGiftCardOffer(BaseModel):
    """A gift card offer as returned by the GameBoost API.

    Gift card offers link to a catalog gift card and have stock + pricing.
    No list/unlist/archive lifecycle — just create/update/delete.
    """

    id: int = 0
    gift_card_id: int = 0
    price_eur: str | dict | None = ""
    price_usd: str | dict | None = ""
    stock: int = 0
    gift_card: GameBoostGiftCard = Field(default_factory=GameBoostGiftCard)
    created_at: int | None = None
    updated_at: int | None = None

    model_config = {"populate_by_name": True}


class GameBoostGiftCardAddStockResponse(BaseModel):
    """Response from POST /gift-cards/offers/{id}/stock.

    The exact response shape is not fully documented; fields are permissive.
    """

    message: str = ""
    data: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Gift Card Order model
# ---------------------------------------------------------------------------

class GameBoostGiftCardOrderKey(BaseModel):
    """A single delivered key in a gift card order."""

    id: int = 0
    gift_card_order_id: int = 0
    key: str = ""
    type: dict[str, Any] = Field(default_factory=dict)
    created_at: int | None = None
    revealed_at: int | None = None


class GameBoostGiftCardOrder(BaseModel):
    """A gift card order as returned by the GameBoost API.

    Gift card orders have quantity, string prices, and delivered keys.
    """

    id: int = 0
    gift_card_id: int = 0
    gift_card_offer_id: int | None = None
    region_id: int = 0
    brand_id: int = 0
    buyer: GameBoostBuyer = Field(default_factory=GameBoostBuyer)
    title: str = ""
    face_value_amount: str = ""
    face_value_unit: str = ""
    quantity: int = 0
    unit_price_eur: str | dict | None = ""
    unit_price_usd: str | dict | None = ""
    price_eur: str | dict | None = ""
    price_usd: str | dict | None = ""
    status: str = ""
    keys: list[GameBoostGiftCardOrderKey] = Field(default_factory=list)
    created_at: int | None = None
    updated_at: int | None = None
    completed_at: int | None = None
    refunded_at: int | None = None

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Currency Offer model
# ---------------------------------------------------------------------------

class GameBoostCurrencyOffer(BaseModel):
    """A currency offer as returned by the GameBoost API.

    Currency offers sell in-game currency (e.g. gold, Robux) with per-unit pricing.
    They have list/unlist/archive lifecycle like item offers.
    """

    id: int = 0
    uuid: str = ""
    external_id: str | None = None
    game: GameBoostGame = Field(default_factory=GameBoostGame)
    currency_unit: GameBoostCurrencyUnit | None = None

    title: str = ""
    description: str | None = None
    parameters: dict[str, Any] | list[Any] | None = None
    base_currency: str = ""

    status: str = ""
    delivery_time: GameBoostDeliveryTime = Field(default_factory=GameBoostDeliveryTime)
    delivery_instructions: str | None = None

    stock: int = 0
    min_quantity: int = 1

    price_eur: str | dict | None = ""
    price_usd: str | dict | None = ""

    views: int = 0
    icon_url: str | None = None

    created_at: int | None = None
    updated_at: int | None = None
    listed_at: int | None = None

    model_config = {"populate_by_name": True}


class GameBoostCurrencyOfferActionResponse(BaseModel):
    """Response from list/unlist/archive currency offer actions."""

    data: GameBoostCurrencyOffer = Field(default_factory=GameBoostCurrencyOffer)
    message: str = ""
    action: str = ""
    previous_status: str | None = None


class GameBoostCurrencyOfferTemplate(BaseModel):
    """Template for creating a currency offer for a specific game."""

    game: str = ""
    description: str = ""
    price: float = 0.0
    currency: str = ""
    stock: int = 0
    min_quantity: int = 1
    delivery_time: dict[str, Any] = Field(default_factory=dict)
    delivery_instructions: str = ""
    currency_data: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Currency Order model
# ---------------------------------------------------------------------------

class GameBoostCurrencyOrder(BaseModel):
    """A currency order as returned by the GameBoost API.

    Currency orders have quantity, per-unit prices, and optional credentials/proof.
    """

    id: int = 0
    currency_offer_id: int | None = None
    game: GameBoostGame = Field(default_factory=GameBoostGame)
    buyer: GameBoostBuyer = Field(default_factory=GameBoostBuyer)
    rating: Any = None
    title: str = ""
    description: str | None = None
    quantity: int = 0
    currency_unit: GameBoostCurrencyUnit | None = None
    parameters: dict[str, Any] | list[Any] | None = None
    status: str = ""

    delivery_time: GameBoostDeliveryTime = Field(default_factory=GameBoostDeliveryTime)
    credentials: Any = None
    completion_proof_url: str | None = None

    price_eur: str | dict | None = ""
    price_usd: str | dict | None = ""
    unit_price_eur: str | dict | None = ""
    unit_price_usd: str | dict | None = ""

    created_at: int | None = None
    updated_at: int | None = None

    model_config = {"populate_by_name": True}


class GameBoostCurrencyOrderActionResponse(BaseModel):
    """Response from complete currency order action."""

    data: GameBoostCurrencyOrder = Field(default_factory=GameBoostCurrencyOrder)
    message: str = ""
    action: str = ""


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class GameBoostPaginationMeta(BaseModel):
    """Pagination metadata from GameBoost list responses.

    Matches the real ``meta`` block in paginated responses:
    ``current_page``, ``last_page``, ``per_page``, ``total``, ``from``, ``to``, ``path``.
    """

    current_page: int = 1
    last_page: int = 0
    per_page: int = 15
    total: int = 0
    # ``from`` and ``to`` indicate the item range on the current page
    from_: int | None = Field(default=None, alias="from")
    to: int | None = None
    path: str = ""

    model_config = {"populate_by_name": True}

    @property
    def has_next(self) -> bool:
        return self.current_page < self.last_page

    @property
    def has_prev(self) -> bool:
        return self.current_page > 1

    @property
    def total_pages(self) -> int:
        """Alias for ``last_page`` for convenience."""
        return self.last_page
