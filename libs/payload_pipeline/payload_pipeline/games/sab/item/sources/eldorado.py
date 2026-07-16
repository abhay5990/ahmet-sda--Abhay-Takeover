"""Eldorado source adapter for SAB items."""
from __future__ import annotations
import logging
import re
from urllib.parse import quote as _url_quote

logger = logging.getLogger(__name__)
_ELDORADO_CDN = "https://assetsdelivery.eldorado.gg/v7/_offers_/{filename}"

# Marketing noise to strip from seller titles when used as fallback item name
_NOISE = re.compile(
    r"(instant|premium|fast|quick)\s+(delivery|trade|sell|buy|stock)"
    r"|24\s*/\s*7"
    r"|\binstant\b|\bdelivery\b|\btrade\b|\btrusted\b|\bseller\b|\bpremium\b"
    r"|\bfast\b|\bquick\b|\bcheap\b|\bbest\b|\bprice\b|\bstock\b"
    r"|\d+\s*[MmBbKk]/[Ss]"   # drop M/s values — we render them ourselves
    r"|\bcandy\b",             # "candy " prefix used by this seller
    re.IGNORECASE,
)
_EMOJI = re.compile(
    r"[\U00010000-\U0010FFFF"   # supplementary planes (most game emoji)
    r"\U0001F000-\U0001FAFF"
    r"\u2600-\u27BF"
    r"\uFE00-\uFE0F"
    r"]+",
    flags=re.UNICODE,
)


def _clean_seller_title(t: str) -> str:
    if not t:
        return ""
    t = _NOISE.sub("", t)          # drop marketing phrases
    t = _EMOJI.sub("", t)          # drop emoji
    t = re.sub(r"[|#@!?*\"']+", "", t)  # drop punctuation noise
    t = re.sub(r"\s{2,}", " ", t).strip()
    return t


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
            return _ELDORADO_CDN.format(filename=_url_quote(filename, safe=""))
    # Fallback: first offerImages entry
    offer_images = raw.get("offerImages") or []
    if offer_images and isinstance(offer_images[0], dict):
        filename = offer_images[0].get("largeImage") or offer_images[0].get("originalSizeImage")
        if filename:
            return _ELDORADO_CDN.format(filename=_url_quote(filename, safe=""))
    return ""


class SabEldoradoSourceAdapter:
    def parse(self, raw: dict) -> dict | None:
        if not raw:
            return None
        offer_id = str(raw.get("id", "") or raw.get("offerId", ""))
        if not offer_id:
            return None

        price_data = raw.get("minPurchasePrice") or raw.get("pricePerUnitInUSD") or raw.get("price") or {}
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

        # item_name: check structured attributes first (Brainrot, Pets & Eggs, name, item_name)
        # then fall back to a cleaned seller title
        item_name = (
            attrs.get("brainrot")        # most Brainrot items
            or attrs.get("pets_&_eggs")  # Pets items (Stygian Owl, Blue Betta Fish, etc.)
            or attrs.get("item_name")
            or attrs.get("name")
            or ""
        )
        # If structured lookup returned "Other" or empty, use cleaned seller title
        if not item_name or item_name.lower() == "other":
            item_name = _clean_seller_title(raw.get("offerTitle") or raw.get("title", ""))

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
