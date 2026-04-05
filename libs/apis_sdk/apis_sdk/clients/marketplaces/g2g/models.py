"""
G2G API response models.

These represent the raw API contract with G2G.
Models use permissive defaults so that missing fields don't
cause parse failures — the API may return partial data.

G2G responses use an internal envelope structure:
  {"code": 2000, "payload": {...}, "messages": [...]}
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class G2GMessage(BaseModel):
    """A message entry in a G2G API response."""

    code: int = 0
    type: str = ""
    text: str = ""


class G2GEnvelope(BaseModel):
    """G2G API response envelope.

    All G2G API responses wrap their data in this structure.
    ``code`` is the G2G-internal response code (not HTTP status).
    """

    code: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)
    messages: list[G2GMessage] = Field(default_factory=list)


class G2GOffer(BaseModel):
    """An offer as returned by the G2G API."""

    offer_id: str = ""
    relation_id: str = ""
    title: str = ""
    description: str = ""
    unit_price: float = 0.0
    currency: str = "USD"
    qty: int = 0
    min_qty: int = 1
    status: str = ""
    delivery_method_ids: list[str] = Field(default_factory=list)
    delivery_speed: str = ""
    offer_type: str = ""
    brand_id: str = ""
    service_id: str = ""
    created_at: int | str = ""
    updated_at: int | str = ""
    offer_attributes: list[dict[str, Any]] = Field(default_factory=list)
    external_images_mapping: list[dict[str, str]] = Field(default_factory=list)
