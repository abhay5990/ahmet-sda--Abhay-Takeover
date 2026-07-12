from __future__ import annotations
import re
from payload_pipeline.marketplaces.base import BasePayloadBuilder


def _slugify(text):
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "-", slug)
    return slug.strip("-")


class SabItemGameBoostBuilder(BasePayloadBuilder):
    marketplace = "gameboost"

    def build_payload(self, subject, listing, ctx):
        content = listing.get("gameboost", {}) if isinstance(listing, dict) else {}
        title = content.get("title", subject.item_name or "SAB Item")
        description = content.get("description", "")

        # Append #DS tag to mark as dropship listing
        if "#DS" not in title:
            title = f"{title} #DS"

        # Apply pricing rules (multiplier) then exchange rate — same as BaseBuilder pattern
        price = self._apply_pricing(subject.price, ctx)
        if ctx.exchange_rate is not None:
            price = round(price * ctx.exchange_rate, 2)

        image_urls = [subject.image_url] if getattr(subject, "image_url", None) else []

        return {
            "game": "steal-a-brainrot",
            "title": title,
            "slug": _slugify(title),
            "description": description,
            "price": price,
            # Required fields for item offers
            "stock": 1,
            "min_quantity": 1,
            # Delivery: none — we contact buyer via chat
            "delivery_method": "none",
            "delivery_time": {"duration": 20, "unit": "minutes"},
            "delivery_instructions": (
                "\u26a1 INSTANT DELIVERY\n"
                "After purchase, contact us via chat with your order ID. "
                "We will deliver your item within 10 minutes."
            ),
            "image_urls": image_urls,
        }
