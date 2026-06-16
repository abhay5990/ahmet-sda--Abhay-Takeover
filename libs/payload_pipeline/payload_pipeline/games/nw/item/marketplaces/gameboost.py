"""GameBoost item builder for New World.

Template reference: ``assets/gameboost_templates/items/new-world.json``
  - game slug: new-world
  - item_data: server (string from predefined list)
  - No login/password in payload — credentials go into delivery_instructions.

This builder uses the GameBoost *item* payload format (stock + item_data),
which differs from the account format used by BaseGameBoostBuilder.
"""

from __future__ import annotations

import re
from typing import Any

from ..models import NwResolvedItem
from .....core.contracts import BuildContext, ListingDraft
from .....core.enums import ListingKind
from .....marketplaces.base import BasePayloadBuilder, _DISCLAIMER, _DROPSHIPPING_DELIVERY


def _slugify(text: str) -> str:
    """Convert title to a URL-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "-", slug)
    return slug.strip("-")


class NwItemGameBoostBuilder(BasePayloadBuilder[NwResolvedItem]):
    """Build GameBoost item payloads for New World."""

    marketplace = "gameboost"

    def build_payload(
        self,
        subject: NwResolvedItem,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        content = listing.content_for(self.marketplace, ref_key=subject.ref_key)
        price = self._apply_pricing(subject.price, ctx)
        if ctx.exchange_rate is not None:
            price = round(price * ctx.exchange_rate, 2)
        is_stock = ctx.kind == ListingKind.STOCK

        delivery_instructions = (
            self._standard_delivery(subject.credentials, "New World Account")
            if is_stock
            else _DROPSHIPPING_DELIVERY
        )

        return {
            "game": "new-world",
            "title": content.title,
            "slug": _slugify(content.title),
            "description": content.description,
            "price": price,
            "stock": 1,
            "delivery_time": {"duration": 10, "unit": "minutes"},
            "delivery_instructions": delivery_instructions,
            "image_urls": [],
            "item_data": {
                "server": subject.region or "North America",
            },
        }
