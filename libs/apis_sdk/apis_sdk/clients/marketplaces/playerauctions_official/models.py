"""
PlayerAuctions Official Seller API response models.

Official API response envelope:
    {
      "code": 10000,        # 10000 = success, anything else = error
      "message": "...",
      "requestId": "...",
      "data": { ... }
    }

Error code ranges:
    1xxxx = parameter errors
    2xxxx = signature errors
    3xxxx = authentication/authorization errors
    4xxxx = business rule errors
    5xxxx = server errors
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------

class PAErrorCode(IntEnum):
    """Known PA Official API error codes."""

    SUCCESS = 10000
    MISSING_HEADER = 10001
    INVALID_PARAMETER = 10002
    INVALID_SIGNATURE = 20001
    AUTHENTICATION_ERROR = 30001
    AUTHORIZATION_ERROR = 30002
    BUSINESS_ERROR = 40001
    INTERNAL_SERVER_ERROR = 50001


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

class PAEnvelope(BaseModel):
    """Standard response envelope from the official PA API."""

    code: int = 0
    message: str = ""
    request_id: str = Field(default="", alias="requestId")
    data: Any = None

    model_config = {"populate_by_name": True}

    @property
    def is_success(self) -> bool:
        return self.code == PAErrorCode.SUCCESS


# ---------------------------------------------------------------------------
# Offer models
# ---------------------------------------------------------------------------

class PAOfferListItem(BaseModel):
    """An offer from the list offers endpoint (GET /api/v1/offers)."""

    offer_id: int = Field(default=0, alias="offerId")
    system_status: str = Field(default="", alias="systemStatus")
    offer_status: str = Field(default="", alias="offerStatus")
    title: str = ""
    game_name: str = Field(default="", alias="gameName")
    delivery_guarantee: str = Field(default="", alias="deliveryGuarantee")
    total_price: str = Field(default="", alias="totalPrice")
    expired_time_string: str = Field(default="", alias="expiredTimeString")
    product_type: str = Field(default="", alias="productType")
    url: str = ""

    model_config = {"populate_by_name": True}


class PAOfferDetail(BaseModel):
    """Full offer detail from query single offer endpoints.

    Contains all create/edit fields plus state metadata.
    Uses permissive defaults since different product types return
    different field sets.
    """

    offer_id: int = Field(default=0, alias="offerId")
    member_id: int = Field(default=0, alias="memberId")
    game_id: int = Field(default=0, alias="gameId")
    state: int = 0  # 0=closed, 1=active, 3=hidden
    product_type: str = Field(default="", alias="productType")
    title: str = ""
    offer_desc: str = Field(default="", alias="offerDesc")
    price: float = 0.0
    offer_duration: int = Field(default=0, alias="offerDuration")
    total_unit: int = Field(default=0, alias="totalUnit")

    # Extra fields preserved as-is for product-type-specific data
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Create/Edit response
# ---------------------------------------------------------------------------

class PACreateOfferResponse(BaseModel):
    """Response data from create/edit offer endpoints."""

    offer_id: int | None = Field(default=None, alias="offerId")
    navigate_url: str = Field(default="", alias="navigateURL")
    title: str = ""
    product_type: str = Field(default="", alias="productType")
    game_name: str = Field(default="", alias="gameName")
    product_name: str = Field(default="", alias="productName")
    screen_shot: str = Field(default="", alias="screenShot")
    image_blacklist: str = Field(default="", alias="imageBlacklist")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Game metadata models
# ---------------------------------------------------------------------------

class PAGame(BaseModel):
    """A game from the games list endpoint."""

    game_id: int = Field(default=0, alias="gameId")
    game_name: str = Field(default="", alias="gameName")
    seo_name: str = Field(default="", alias="seoName")
    cur_name: str = Field(default="", alias="curName")
    cur_suffix: str = Field(default="", alias="curSuffix")
    product_type: str = Field(default="", alias="productType")
    is_security_qa_required: int = Field(default=0, alias="isSecurityQARequired")
    is_cd_key_required: int = Field(default=0, alias="isCDKeyRequired")
    is_parental_psw_required: int = Field(default=0, alias="isParentalPswRequired")
    is_involve_exploits_game: bool = Field(default=False, alias="isInvolveExploitsGame")
    is_m_currency_type: bool = Field(default=False, alias="isMCurrencyType")

    model_config = {"populate_by_name": True}


class PAServerNode(BaseModel):
    """A server/faction node from the server tree endpoint."""

    id: int = 0
    product_type: str = Field(default="", alias="productType")
    name: str = ""
    seo_name: str = Field(default="", alias="seoName")
    parent_id: int = Field(default=0, alias="parentId")
    item_suffix: str = Field(default="", alias="itemSuffix")
    sequence: int = 0
    sub_categorys: list[PAServerNode] = Field(
        default_factory=list, alias="subCategorys"
    )

    model_config = {"populate_by_name": True}


class PADeliveryTime(BaseModel):
    """A delivery time option from the delivery times endpoint."""

    custom_id: int = Field(default=0, alias="customId")
    time: int = 0
    convert_to_hour: float = Field(default=0.0, alias="convertToHour")
    unit: str = ""
    is_enable: bool = Field(default=True, alias="isEnable")

    model_config = {"populate_by_name": True}


class PACurrencyType(BaseModel):
    """A currency type from multi-currency games."""

    currency_type_id: int = Field(default=0, alias="currencyTypeId")
    currency_name: str = Field(default="", alias="currencyName")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Prevalidation
# ---------------------------------------------------------------------------

class PAPrevalidation(BaseModel):
    """Seller eligibility from creation-prevalidation endpoint."""

    member_id: int = Field(default=0, alias="memberId")
    status: str = ""
    member_class: str = Field(default="", alias="memberClass")
    seller_level: str = Field(default="", alias="sellerLevel")
    is_allow_currency_upload: bool = Field(default=False, alias="isAllowCurrencyUpload")
    is_allow_item_upload: bool = Field(default=False, alias="isAllowItemUpload")
    is_allow_account_upload: bool = Field(default=False, alias="isAllowAccountUpload")
    is_warning_tip_sanctions: bool = Field(default=False, alias="isWarningTipSanctions")
    is_seller: bool = Field(default=False, alias="isSeller")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Cancel / Display status
# ---------------------------------------------------------------------------

class PACancelRequest(BaseModel):
    """Request body for cancel or display-status endpoints."""

    offer_ids: list[int] = Field(default_factory=list, alias="offerIds")
    is_all: bool = Field(default=False, alias="isAll")
    parameters: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class PADisplayStatusRequest(BaseModel):
    """Request body for the display-status endpoint."""

    offer_ids: list[int] = Field(default_factory=list, alias="offerIds")
    flag: str = "hide"  # "hide" or "display"
    is_all: bool = Field(default=False, alias="isAll")
    parameters: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Bulk upload
# ---------------------------------------------------------------------------

class PABulkUploadResponse(BaseModel):
    """Response from bulk upload endpoint."""

    offer_total_count: int = Field(default=0, alias="offerTotalCount")
    offers: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Media / Images
# ---------------------------------------------------------------------------

class PAImageUploadResponse(BaseModel):
    """Response from image upload endpoint."""

    blob_name: str = Field(default="", alias="blobName")
    sas_uri: str = Field(default="", alias="sasUri")
    created: str = ""
    length: int = 0
    verified: bool = False

    model_config = {"populate_by_name": True}
