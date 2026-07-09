from __future__ import annotations
import re

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
        if hasattr(ctx, "apply_multiplier"):
            price = ctx.apply_multiplier(price)
        elif hasattr(ctx, "multiplier") and ctx.multiplier:
            price = round(price * ctx.multiplier, 2)
        if hasattr(ctx, "exchange_rate") and ctx.exchange_rate:
            price = round(price * ctx.exchange_rate, 2)

        # Build account_data using GameBoost SAB template fields
        account_data = {
            "money_amount": "0",
            "secrets_amount": 0,
            "rebirths_amount": 0,
            "floor": None,
        }
        if subject.rarity:
            account_data["rarity"] = subject.rarity
        if subject.ms_min > 0:
            if subject.ms_max > subject.ms_min:
                account_data["ms"] = f"{subject.ms_min:.1f}-{subject.ms_max:.1f}"
            else:
                account_data["ms"] = f"{subject.ms_min:.1f}"
        if subject.mutations:
            account_data["mutations"] = ", ".join(subject.mutations)

        image_urls = [subject.image_url] if getattr(subject, "image_url", None) else []

        return {
            "game": "steal-a-brainrot",
            "title": title,
            "slug": _slugify(title),
            "description": description,
            "price": price,
            # credentials array is required by the /create endpoint
            "credentials": ["Delivery: Manual - Contact us after purchase via chat"],
            "is_manual": True,
            "delivery_time": {"duration": 10, "unit": "minutes"},
            "has_2fa": False,
            "level_up_method": "by_hand",
            "image_urls": image_urls,
            "account_data": account_data,
            "delivery_instructions": (
                "\u26a1 INSTANT DELIVERY\n"
                "After purchase, contact us via chat with your order ID. "
                "We will deliver your item within 10 minutes."
            ),
        }
