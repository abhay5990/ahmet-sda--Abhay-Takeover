"""Normalize marketplace create responses to sync-compatible raw_data."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.utils import timezone

from core.marketplace.enrichment import (
    build_eldorado_credential_entries,
    build_gameboost_credential_entries,
)

logger = logging.getLogger(__name__)


def normalize_offer_response(
    marketplace: str,
    response_data: Any,
    *,
    payload: dict[str, Any] | None = None,
    client: Any = None,
    proxy_group: str | None = None,
) -> dict[str, Any]:
    """Convert a marketplace create response to the raw_data shape sync writes."""
    data = _to_dict(response_data)
    marketplace = str(marketplace or "").lower()

    if marketplace == "eldorado":
        return _normalize_eldorado(data, payload)
    if marketplace == "gameboost":
        return _normalize_gameboost(data, payload)
    if marketplace == "playerauctions":
        return _normalize_playerauctions(
            data,
            payload,
            client=client,
            proxy_group=proxy_group,
        )
    return data


def _normalize_eldorado(
    data: dict[str, Any],
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    result = dict(data)

    if payload and not result.get("_credential_entries"):
        secrets = payload.get("accountSecretDetails", [])
        entries = build_eldorado_credential_entries(secrets)
        if entries:
            result["_credential_entries"] = entries

    return result


def _normalize_gameboost(
    data: dict[str, Any],
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    inner = data.get("data")
    result = dict(inner) if isinstance(inner, dict) else dict(data)

    if payload and not result.get("_credential_entries"):
        credentials = payload.get("credentials")
        if isinstance(credentials, list) and credentials:
            result["_credential_entries"] = build_gameboost_credential_entries(
                credentials,
                account_offer_id=result.get("id", 0),
            )

    return result


def _normalize_playerauctions(
    data: dict[str, Any],
    payload: dict[str, Any] | None,
    *,
    client: Any = None,
    proxy_group: str | None = None,
) -> dict[str, Any]:
    inner = data.get("data") if isinstance(data.get("data"), dict) else data
    offer_id = str(
        inner.get("offerId")
        or inner.get("offer_id")
        or inner.get("id")
        or ""
    ).strip()
    if not offer_id:
        return data

    # Use existing details from data (sync pre-enriches), fetch only if missing
    details = inner.get("details") if isinstance(inner.get("details"), dict) else None
    if not details:
        details = _fetch_pa_details(
            offer_id,
            client=client,
            proxy_group=proxy_group,
        )

    title = str(inner.get("title") or "").strip()
    if not title and payload:
        title = str(payload.get("Title") or payload.get("title") or "").strip()

    system_status = str(
        inner.get("system_status")
        or inner.get("systemStatus")
        or "Active"
    ).strip()

    result: dict[str, Any] = {
        "offer_id": _to_int(offer_id),
        "system_status": system_status,
        "title": title,
        "total_price": "",
        "delivery_guarantee": "",
        "expired_time_string": "",
    }

    if not details:
        # Preserve existing fields when details unavailable
        for field in ("total_price", "delivery_guarantee", "expired_time_string"):
            val = inner.get(field)
            if val:
                result[field] = val
        return result

    result["details"] = details
    price = _to_float(details.get("price"))
    if price is not None:
        result["total_price"] = f"${price:.2f}"

    result["delivery_guarantee"] = "Instant" if details.get("isAuto") else ""

    # Preserve existing expiry from sync data; only calculate for new offers
    existing_expiry = str(
        inner.get("expired_time_string")
        or inner.get("expiredTimeString")
        or ""
    ).strip()
    if existing_expiry:
        result["expired_time_string"] = existing_expiry
    else:
        duration_days = _to_int(details.get("offerDuration"), default=30)
        expire_dt = timezone.now() + timedelta(days=duration_days)
        result["expired_time_string"] = expire_dt.strftime("%b-%d-%Y %I:%M:%S %p")

    return result


def _fetch_pa_details(
    offer_id: str,
    *,
    client: Any = None,
    proxy_group: str | None = None,
) -> dict[str, Any] | None:
    if not client:
        return None
    try:
        result = client.get_offer_details(
            offer_id=offer_id,
            proxy_group=proxy_group,
        )
        if result.ok and isinstance(result.data, dict) and result.data:
            return result.data
    except Exception:
        logger.warning("PA detail fetch failed for offer %s", offer_id, exc_info=True)
    return None


def _to_dict(data: Any) -> dict[str, Any]:
    if data is None:
        return {}
    if hasattr(data, "model_dump"):
        return data.model_dump()
    if hasattr(data, "dict"):
        return data.dict()
    if isinstance(data, dict):
        return data
    return {}


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any, *, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default

