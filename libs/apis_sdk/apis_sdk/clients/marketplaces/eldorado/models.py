"""
Eldorado API request and response models.

These represent the raw API contract with Eldorado.
They are mapped to SDK-canonical types via the mapper module.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Offer models
# ---------------------------------------------------------------------------

class EldoradoOfferImage(BaseModel):
    """Image triplet (small, large, original) as used by Eldorado."""

    smallImage: str = ""
    largeImage: str = ""
    originalSizeImage: str = ""


class EldoradoPricePerUnit(BaseModel):
    """Price per unit for an Eldorado offer."""

    amount: float = 0.0
    currency: str = "USD"


class EldoradoPricing(BaseModel):
    """Pricing details for an Eldorado offer."""

    quantity: int = 1
    minQuantity: int = 1
    pricePerUnit: EldoradoPricePerUnit = Field(default_factory=EldoradoPricePerUnit)
    volumeDiscounts: list[dict[str, object]] = Field(default_factory=list)


class EldoradoOfferDetails(BaseModel):
    """The 'details' block of an Eldorado offer."""

    pricing: EldoradoPricing = Field(default_factory=EldoradoPricing)
    description: str = ""
    guaranteedDeliveryTime: str = "Instant"
    offerTitle: str = ""
    mainOfferImage: EldoradoOfferImage = Field(default_factory=EldoradoOfferImage)
    offerImages: list[EldoradoOfferImage] = Field(default_factory=list)
    hasOriginalEmail: bool | None = False
    tags: list[str] = Field(default_factory=list)


class EldoradoAugmentedGame(BaseModel):
    """Game/category targeting for an Eldorado offer."""

    gameId: str = ""
    category: str = "Account"
    tradeEnvironmentId: str | None = None
    attributeIdsCsv: str = ""
    attributes: dict[str, str] = Field(default_factory=dict)


class EldoradoOffer(BaseModel):
    """Full Eldorado offer as returned by create/update endpoints."""

    id: str = ""
    details: EldoradoOfferDetails = Field(default_factory=EldoradoOfferDetails)
    augmentedGame: EldoradoAugmentedGame = Field(default_factory=EldoradoAugmentedGame)
    accountSecretDetails: str | list[str] | None = None
    status: str = ""
    createdAt: str = ""
    updatedAt: str = ""


# ---------------------------------------------------------------------------
# Offer search models (flat structure from /flexibleOffers/me/search)
# ---------------------------------------------------------------------------

class EldoradoOfferAccountDetail(BaseModel):
    """Single credential entry within an offer's accountsDetails array."""

    id: str = ""
    secretDetails: str = ""


class EldoradoOfferSearchItem(BaseModel):
    """A single offer as returned by the search endpoint.

    The search endpoint returns a flat structure (unlike the nested
    create/update response captured by ``EldoradoOffer``).
    """

    model_config = {"extra": "allow"}

    id: str = ""
    userId: str = ""
    gameId: str = ""
    category: str = ""
    gameCategoryTitle: str = ""
    offerTitle: str = ""
    description: str = ""
    offerState: str = ""
    guaranteedDeliveryTime: str = ""
    quantity: int = 1
    minQuantity: int = 1
    pricePerUnit: EldoradoPricePerUnit = Field(default_factory=EldoradoPricePerUnit)
    pricePerUnitWithDiscount: EldoradoPricePerUnit | None = None
    pricePerUnitInUSD: EldoradoPricePerUnit | None = None
    discountPercentage: float | None = None
    volumeDiscounts: list[dict[str, object]] = Field(default_factory=list)
    mainOfferImage: EldoradoOfferImage | None = None
    offerImages: list[EldoradoOfferImage] = Field(default_factory=list)
    hasOriginalEmail: bool | None = False
    expireDate: str | None = None
    offerVersion: int = 0
    accountsDetails: list[EldoradoOfferAccountDetail] = Field(default_factory=list)


class EldoradoOfferSearchPage(BaseModel):
    """Paginated response from the offer search endpoint."""

    pageIndex: int = 1
    totalPages: int = 0
    recordCount: int = 0
    pageSize: int = 40
    results: list[EldoradoOfferSearchItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Shared nested models
# ---------------------------------------------------------------------------

class EldoradoMoney(BaseModel):
    """Amount + currency pair used across Eldorado responses."""

    amount: float = 0.0
    currency: str = "USD"


class EldoradoStateEntry(BaseModel):
    """A single state entry (used in current state and stateLogs)."""

    state: str = ""
    createdDate: str = ""


# ---------------------------------------------------------------------------
# Order models
# ---------------------------------------------------------------------------

class EldoradoOrder(BaseModel):
    """
    An Eldorado order as returned by the seller orders list or single-order endpoint.

    Fields present in the list endpoint have defaults; fields only present in
    the detail endpoint (buyerInfo, sellerInfo, sellerPayments, etc.) are
    captured by extra="allow" so nothing is silently dropped.
    """

    model_config = {"extra": "allow"}

    # Core identifiers
    id: str = ""
    sellerId: str = ""
    buyerId: str = ""
    offerId: str = ""

    # List-only convenience fields
    buyerUsername: str | None = None
    sellerUsername: str | None = None

    # Quantity & pricing
    purchaseQuantity: int = 0
    totalPrice: EldoradoMoney = Field(default_factory=EldoradoMoney)
    totalPriceInUsersCurrency: EldoradoMoney | None = None
    systemDiscount: EldoradoMoney | None = None
    systemDiscountInUsersCurrency: EldoradoMoney | None = None

    # State
    state: EldoradoStateEntry = Field(default_factory=EldoradoStateEntry)
    stateLogs: list[EldoradoStateEntry] = Field(default_factory=list)

    # Offer details snapshot (complex nested — kept as dict to avoid overfit)
    orderOfferDetails: dict[str, object] | None = None

    # Delivery
    deliveryOptions: dict[str, object] | None = None
    deliveryTime: str | None = None
    deliveryStartedDate: str | None = None

    # Review
    review: dict[str, object] | None = None

    # Dispute
    dispute: dict[str, object] | None = None
    latestDispute: dict[str, object] | None = None

    # Conversation
    talkJsConversationId: str | None = None
    conversationDetails: dict[str, object] | None = None

    # Timestamps
    createdDate: str = ""

    # Flags
    isHistorical: bool = False
    hasBeenRefundedPostCompletion: bool = False
    canBeRefundedPostCompletion: bool = False
    isEligibleForWarranty: bool | None = None
    isWithWarranty: bool = False
    warrantyDuration: str | None = None

    # Cancellation
    cancelation: dict[str, object] | None = None

    # Misc
    disputeReceivedBy: str | dict[str, object] | None = None
    userRequestDetails: dict[str, object] | None = None
    sitewideSaleDiscount: EldoradoMoney | None = None
    sitewideSaleDiscountInUsersCurrency: EldoradoMoney | None = None


class EldoradoSellerOrdersPage(BaseModel):
    """Paginated response from the seller orders list endpoint."""

    cursor: str | None = None
    pageDirection: str = ""
    previousPageCursor: str | None = None
    nextPageCursor: str | None = None
    pageSize: int = 20
    results: list[EldoradoOrder] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Image upload response
# ---------------------------------------------------------------------------

class EldoradoOfferStateCount(BaseModel):
    """State counts for offers grouped by game/category."""

    active: int = 0
    inactive: int = 0
    pending: int = 0
    suspended: int = 0


class EldoradoOrderAccountDetails(BaseModel):
    """Account details returned for a completed order."""

    id: str = ""
    secretDetails: str = ""


class EldoradoOfferCredentialsResponse(BaseModel):
    """Response from GET /api/offers/accountDetails/byOfferId/{offer_id}.

    Contains both ``accountsDetails`` and ``secretDetails`` arrays
    (typically identical content).
    """

    accountsDetails: list[EldoradoOfferAccountDetail] = Field(default_factory=list)
    secretDetails: list[EldoradoOfferAccountDetail] = Field(default_factory=list)


class EldoradoImageUploadResponse(BaseModel):
    """Response from Eldorado image upload endpoint."""

    paths: list[str] = Field(default_factory=list)
