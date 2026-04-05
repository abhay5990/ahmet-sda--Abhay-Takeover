"""
LZT Market API response models.

Minimal response models.  LZT responses vary significantly by
category, so listing items are kept as raw dicts.  Only stable
pagination / envelope shapes are modelled here.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LztListingPage(BaseModel):
    """Envelope for a paginated category listing response.

    ``items`` contains the raw provider dicts — category-specific
    fields vary too much to model strictly in the SDK.
    """

    items: list[dict[str, Any]] = Field(default_factory=list)
    has_next_page: bool = Field(default=False, alias="hasNextPage")

    model_config = {"populate_by_name": True}


class LztOrderPage(BaseModel):
    """Envelope for user-orders list responses."""

    items: list[dict[str, Any]] = Field(default_factory=list)
    has_next_page: bool = Field(default=False, alias="hasNextPage")
    total_items: int = Field(default=0, alias="totalItems")
    per_page: int = Field(default=40, alias="perPage")
    page: int = Field(default=1)

    model_config = {"populate_by_name": True}


class LztCheckAccountResult(BaseModel):
    """Response from the pre-purchase availability check.

    ``item`` is kept as a raw dict — the shape varies by category.
    """

    status: str = ""
    item: dict[str, Any] = Field(default_factory=dict)
    require_video_recording: bool = Field(
        default=False, alias="requireVideoRecording"
    )

    model_config = {"populate_by_name": True}


class LztPurchaseResult(BaseModel):
    """Response from a successful purchase confirmation.

    ``item`` contains account credentials (login, password, email, etc.)
    and varies by category, so it is kept as a raw dict.
    """

    status: str = ""
    item: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}
