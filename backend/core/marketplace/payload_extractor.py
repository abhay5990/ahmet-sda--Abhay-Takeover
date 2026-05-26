"""Extract create-ready payloads from Listing.raw_data."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def extract_create_payload(
    raw_data: dict[str, Any],
    marketplace: str,
    *,
    client: Any = None,
    proxy_group: str | None = None,
) -> dict[str, Any] | None:
    """Return a marketplace create payload from old or sync-style raw_data."""
    if not raw_data:
        return None

    marketplace = str(marketplace or "").lower()

    payload = raw_data.get("payload")
    if isinstance(payload, dict):
        if marketplace != "playerauctions":
            return payload
        if payload.get("autoDelivery") or payload.get("gameId"):
            return payload

        refetched = _pa_refetch_from_legacy_envelope(
            raw_data,
            client=client,
            proxy_group=proxy_group,
        )
        if refetched:
            return refetched
        return None

    try:
        if marketplace == "eldorado" and ("id" in raw_data or "offerTitle" in raw_data):
            from apis_sdk.clients.marketplaces.eldorado.mapper import EldoradoMapper

            return EldoradoMapper.build_from_raw(raw_data)

        if marketplace == "playerauctions" and (
            "details" in raw_data or "offer_id" in raw_data or "offerId" in raw_data
        ):
            from apis_sdk.clients.marketplaces.playerauctions.mapper import PlayerAuctionsMapper

            pa_raw = _ensure_pa_details(
                raw_data,
                client=client,
                proxy_group=proxy_group,
            )
            if not pa_raw.get("details"):
                logger.warning(
                    "Cannot build PA payload: details missing for offer %s",
                    pa_raw.get("offer_id") or pa_raw.get("offerId"),
                )
                return None
            return PlayerAuctionsMapper.build_from_raw(pa_raw)

        if marketplace == "gameboost" and ("game" in raw_data or "slug" in raw_data):
            from apis_sdk.clients.marketplaces.gameboost.mapper import GameBoostMapper

            return GameBoostMapper.build_from_raw(raw_data)
    except Exception:
        logger.warning("build_from_raw failed for %s", marketplace, exc_info=True)
        return None

    return None


def _pa_refetch_from_legacy_envelope(
    raw_data: dict[str, Any],
    *,
    client: Any = None,
    proxy_group: str | None = None,
) -> dict[str, Any] | None:
    offer_id = _extract_pa_offer_id(raw_data.get("response"))
    if not offer_id:
        return None

    legacy_payload = raw_data.get("payload") if isinstance(raw_data.get("payload"), dict) else {}
    refetched = _ensure_pa_details(
        {
            "offer_id": _to_int(offer_id),
            "title": str(legacy_payload.get("Title") or legacy_payload.get("title") or ""),
        },
        client=client,
        proxy_group=proxy_group,
    )
    if not refetched.get("details"):
        return None

    try:
        from apis_sdk.clients.marketplaces.playerauctions.mapper import PlayerAuctionsMapper

        return PlayerAuctionsMapper.build_from_raw(refetched)
    except Exception:
        logger.warning("build_from_raw failed for playerauctions", exc_info=True)
        return None


def _ensure_pa_details(
    raw_data: dict[str, Any],
    *,
    client: Any = None,
    proxy_group: str | None = None,
) -> dict[str, Any]:
    """Return PA raw_data with details if they can be loaded on demand."""
    if raw_data.get("details") or not client:
        return raw_data

    offer_id = str(raw_data.get("offer_id") or raw_data.get("offerId") or "").strip()
    if not offer_id:
        return raw_data

    try:
        result = client.get_offer_details(offer_id=offer_id, proxy_group=proxy_group)
        if result.ok and isinstance(result.data, dict) and result.data:
            return {**raw_data, "details": result.data}
    except Exception:
        logger.warning("PA detail refetch failed for offer %s", offer_id, exc_info=True)

    return raw_data


def _extract_pa_offer_id(response: Any) -> str:
    if hasattr(response, "model_dump"):
        response = response.model_dump()
    elif hasattr(response, "dict"):
        response = response.dict()

    if not isinstance(response, dict):
        return ""

    nested = response.get("data")
    if isinstance(nested, dict):
        direct = nested.get("offerId") or nested.get("offer_id") or nested.get("id")
        if direct:
            return str(direct)

    return str(response.get("offer_id") or response.get("offerId") or response.get("id") or "")


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
