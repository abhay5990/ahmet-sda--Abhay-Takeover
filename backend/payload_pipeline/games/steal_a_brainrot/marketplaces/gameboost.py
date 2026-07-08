from __future__ import annotations
import re
from typing import Any

def _slugify(text):
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "-", slug)
    return slug.strip("-")

class SabItemGameBoostBuilder:
    marketplace = "gameboost"

    def build_payload(self, subject, listing, ctx):
        content = listing.get("gameboost", {}) if isinstance(listing, dict) else {}
        title = content.get("title", subject.item_name or "SAB Item")
        description = content.get("description", "")
        price = subject.price
        if hasattr(ctx, 'apply_multiplier'):
            price = ctx.apply_multiplier(price)
        elif hasattr(ctx, 'multiplier') and ctx.multiplier:
            price = round(price * ctx.multiplier, 2)
        if hasattr(ctx, 'exchange_rate') and ctx.exchange_rate:
            price = round(price * ctx.exchange_rate, 2)
        item_data = {}
        if subject.rarity: item_data["rarity"] = subject.rarity.lower()
        if subject.ms_min > 0:
            if subject.ms_max > subject.ms_min:
                item_data["ms"] = f"{subject.ms_min:.1f}-{subject.ms_max:.1f}"
            else:
                item_data["ms"] = f"{subject.ms_min:.1f}"
        if subject.mutations: item_data["mutations"] = ", ".join(subject.mutations)
        return {
            "game": "steal-a-brainrot",
            "title": title,
            "slug": _slugify(title),
            "description": description,
            "price": price,
            "stock": subject.quantity,
            "delivery_time": {"duration": 10, "unit": "minutes"},
            "image_urls": [subject.image_url] if subject.image_url else [],
            "item_data": item_data,
        }
