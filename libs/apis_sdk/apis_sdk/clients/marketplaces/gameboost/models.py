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
