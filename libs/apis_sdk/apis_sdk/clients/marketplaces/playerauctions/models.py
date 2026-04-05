"""
PlayerAuctions API response models.

These represent the raw API contract with PlayerAuctions.
Models use permissive defaults so that missing fields don't
cause parse failures — the API may return partial data.

PlayerAuctions responses have provider-specific semantics:
- HTTP 200 does not guarantee success
- ``isSuccess`` field may be ``false`` on a 200 response
- ``StatusCode`` field may contain a non-200 API-level status
- Error details are in ``message`` and ``code`` fields

Order models:
- ``PlayerAuctionsOrderListItem``: flat shape from list endpoint (data.items[])
- ``PlayerAuctionsOrderDetail``: rich nested shape from detail endpoint (data)
- The old ``PlayerAuctionsOrder`` is kept as an alias for ``PlayerAuctionsOrderListItem``
  to maintain backward compatibility.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PlayerAuctionsPagination(BaseModel):
    """Pagination metadata from PlayerAuctions list responses."""

    current_page: int = Field(default=1, alias="currentPage")
    total_pages: int = Field(default=0, alias="totalPages")
    page_size: int = Field(default=50, alias="pageSize")
    total_count: int = Field(default=0, alias="totalCount")

    model_config = {"populate_by_name": True}


class PlayerAuctionsOffer(BaseModel):
    """An offer as returned by the PlayerAuctions list/detail API."""

    offer_id: int = Field(default=0, alias="offerId")
    system_status: str = Field(default="", alias="systemStatus")
    title: str = ""
    delivery_guarantee: str = Field(default="", alias="deliveryGuarantee")
    total_price: str = Field(default="", alias="totalPrice")
    expired_time_string: str = Field(default="", alias="expiredTimeString")
    details: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Order list item — flat shape from /api/Order/SellerOrders → data.items[]
# ---------------------------------------------------------------------------

class PlayerAuctionsOrderListItem(BaseModel):
    """An order item from the seller orders list endpoint.

    This is the flat shape returned in ``data.items[]``.
    Note: ``status`` is a plain string here (e.g. "Pending Payment",
    "Delivery Fully Completed"), unlike the detail endpoint where
    ``status`` is a nested object.
    """

    order_id: int = Field(default=0, alias="orderId")
    order_title: str = Field(default="", alias="orderTitle")
    server_name: str = Field(default="", alias="serverName")
    create_time: str = Field(default="", alias="createTime")
    name: str = ""  # buyer name
    price: str = ""  # formatted price string, e.g. "$190.00"
    product_type: str = Field(default="", alias="productType")
    quantity: str = ""
    status: str = ""  # plain string status
    is_view_details: bool = Field(default=False, alias="isViewdetails")

    model_config = {"populate_by_name": True}


# Backward-compatible alias — existing code importing PlayerAuctionsOrder
# will get the list item model, which is the correct shape for list responses.
PlayerAuctionsOrder = PlayerAuctionsOrderListItem


# ---------------------------------------------------------------------------
# Order detail — rich nested shape from /api/orderdetail/{id} → data
# ---------------------------------------------------------------------------

class PlayerAuctionsOrderStatus(BaseModel):
    """Status object from order detail response."""

    current: str = ""
    current_type: str | None = Field(default=None, alias="currentType")
    order_status: str = Field(default="", alias="orderStatus")

    model_config = {"populate_by_name": True}


class PlayerAuctionsOrderDetail(BaseModel):
    """Order detail as returned by the order detail endpoint.

    This is the full ``data`` object from ``/api/orderdetail/{id}``.
    Contains rich nested structures for order info, delivery,
    disbursement, feedback, event logs, etc.

    Fields that are not explicitly modeled are preserved in ``extra``.
    """

    id: int = 0
    status: PlayerAuctionsOrderStatus = Field(
        default_factory=PlayerAuctionsOrderStatus
    )
    title: str = ""
    tips: str | None = None
    tips_key: str | None = Field(default=None, alias="tipsKey")

    # Visibility / navigation
    is_delivery_info_visible: bool = Field(default=False, alias="isDeliveryInfoVisible")
    view_message_url: str | None = Field(default=None, alias="viewMessageUrl")
    has_message_log: bool = Field(default=False, alias="hasMessageLog")

    # State images
    state_img: dict[str, Any] | None = Field(default=None, alias="stateImg")

    # Actions (buttons like "SEE DISPUTE")
    actions: list[dict[str, Any]] = Field(default_factory=list)

    # Core order data
    order_info: dict[str, Any] = Field(default_factory=dict, alias="orderInfo")
    delivery_info: Any = Field(default=None, alias="deliveryInfo")
    order_cancellation_info: Any = Field(default=None, alias="orderCancellationInfo")
    disbursement_info: dict[str, Any] | None = Field(
        default=None, alias="disbursementInfo"
    )
    refund_info: Any = Field(default=None, alias="refundInfo")
    feedback_info: dict[str, Any] | None = Field(default=None, alias="feedbackInfo")

    # Event log
    event_logs: list[dict[str, Any]] = Field(default_factory=list, alias="eventLogs")

    # Extensions / game account
    extensions: Any = None
    game_account: Any = Field(default=None, alias="gameAccount")

    # Catch-all for any unmodeled fields
    extra: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Request / Response models for write operations
# ---------------------------------------------------------------------------

class PlayerAuctionsCancelRequest(BaseModel):
    """Request shape for cancelling offers on PlayerAuctions."""

    offer_ids: list[int] = Field(alias="offerIds")
    parameters: dict[str, Any] = Field(default_factory=lambda: {
        "keywords": "",
        "listingStatus": "Active",
        "productType": "",
        "serverId": None,
        "factionId": None,
        "gameId": None,
    })
    is_all: bool = Field(default=False, alias="isAll")

    model_config = {"populate_by_name": True}


class PlayerAuctionsCreateOfferResponse(BaseModel):
    """Minimal response model for offer creation."""

    offer_id: int | None = Field(default=None, alias="offerId")

    model_config = {"populate_by_name": True}


class PlayerAuctionsCancelResponse(BaseModel):
    """Minimal response model for offer cancellation."""

    is_success: bool = Field(default=False, alias="isSuccess")
    message: str = ""

    model_config = {"populate_by_name": True}


class PlayerAuctionsBulkUploadResponse(BaseModel):
    """Minimal response model for bulk offer upload.

    The ``offers`` list contains provider-native dicts, each with at
    least an ``offerId`` / ``OfferId`` key.  Individual offer fields
    are intentionally unmodeled — the caller decides what to extract.
    """

    offers: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"populate_by_name": True}
