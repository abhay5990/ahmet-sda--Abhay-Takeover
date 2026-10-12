"""Pure U7Buy seller-order mapping helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.orders.enums import OrderStatus
from core.enums import ProductCategory


_STATUS_MAP = {
    0: OrderStatus.PENDING,
    1: OrderStatus.PENDING,
    2: OrderStatus.PENDING,
    3: OrderStatus.PENDING,
    # U7Buy's “To Receive” state means the buyer has not confirmed the
    # delivery yet.  Keep it non-consuming; only Completed is a sale that may
    # move pool inventory and trigger replenishment.
    4: OrderStatus.PENDING,
    5: OrderStatus.COMPLETED,
    6: OrderStatus.CANCELLED,
}


def extract_remote_id(payload: dict[str, Any]) -> str:
    return str(payload.get("orderId") or payload.get("orderNo") or "").strip()


def extract_listing_id(payload: dict[str, Any]) -> str:
    return str(payload.get("productId") or payload.get("offerId") or "").strip()


def parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric > 10_000_000_000:
        numeric /= 1000
    try:
        return datetime.fromtimestamp(numeric, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def parse_price(payload: dict[str, Any]) -> tuple[Decimal, str]:
    raw = payload.get("priceUsd") or payload.get("price") or payload.get("amount") or "0"
    try:
        price = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        price = Decimal("0")
    return price, str(payload.get("currency") or "USD").upper()[:3]


def map_status(payload: dict[str, Any]) -> str:
    raw = payload.get("orderStatus", payload.get("status"))
    try:
        status = int(raw)
    except (TypeError, ValueError):
        return OrderStatus.PENDING
    return _STATUS_MAP.get(status, OrderStatus.PENDING)


def extract_game_external_id(payload: dict[str, Any]) -> str:
    return str(payload.get("gameId") or payload.get("entityId") or "").strip()


def map_category(_payload: dict[str, Any]) -> str:
    return ProductCategory.ACCOUNTS
