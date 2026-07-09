"""Eldorado source adapter for SAB items."""
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

_ELDORADO_CDN = "https://cdn.eldorado.gg/uploads/offers/{filename}"

def _parse_ms(ms_str: str):
    if not ms_str:
        return 0.0, 0.0
    ms_str = ms_str.strip()
    if "-" in ms_str:
        parts = ms_str.split("-", 1)
        try:
            return float(parts[0].strip()), float(parts[1].strip())
        except ValueError:
            pass
    try:
        val = float(ms_str)
        return val, val
    except ValueError:
        return 0.0, 0.0

def _extract_image_url(raw: dict) -> str:
    """Extract the best image URL from an Eldorado offer dict."""
    main = raw.get("mainOfferImage") or {}
    if isinstance(main, dict):
        filename = main.get("largeImage") or main.get("originalSizeImage") or main.get("smallImage")
        if filename:
            return _ELDORADO_CDN.format(filename=filename)
    # Fallback: first offerImages entry
    offer_images = raw.get("offerImages") or []
    if offer_images and isinstance(offer_images[0], dict):
        filename = offer_images[0].get("largeImage") or offer_images[0].get("originalSizeImage")
        if filename:
            return _ELDORADO_CDN.format(filename=filename)
    return ""

class SabEldoradoSourceAdapter:
    def parse(self, raw: dict) -> dict | None:
        if not raw:
            return None
        offer_id = str(raw.get("id", "") or raw.get("offerId", ""))
        if not offer_id:
            return None
        price_data = raw.get("pricePerUnitInUSD") or raw.get("price") or {}
        if isinstance(price_data, dict):
            price = float(price_data.get("amount", 0) or 0)
        else:
            price = float(price_data or 0)
        trade_values = raw.get("tradeEnvironmentValues") or []
        attrs = {}
        for tv in trade_values:
            key = (tv.get("key") or tv.get("name") or "").lower().replace(" ", "_")
            val = tv.get("value") or ""
            if key:
                attrs[key] = val
        item_name = (
            attrs.get("item_name")
            or attrs.get("brainrot")
            or attrs.get("name")
            or raw.get("title", "")
            or ""
        )
        rarity = attrs.get("rarity", "")
        ms_str = (
            attrs.get("m/s")
            or attrs.get("ms")
            or attrs.get("mutations_per_second")
            or attrs.get("mutations/s")
            or ""
        )
        ms_min, ms_max = _parse_ms(ms_str)
        mutations_raw = attrs.get("mutations", "") or attrs.get("mutation_list", "")
        mutations = [m.strip() for m in mutations_raw.split(",") if m.strip()] if mutations_raw else []
        quantity = int(raw.get("quantity", 1) or 1)
        image_url = _extract_image_url(raw)
        return {
            "offer_id": offer_id,
            "item_name": item_name,
            "rarity": rarity,
            "ms_min": ms_min,
            "ms_max": ms_max,
            "mutations": mutations,
            "price": price,
            "quantity": quantity,
            "image_url": image_url,
        }
