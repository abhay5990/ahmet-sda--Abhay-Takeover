"""GameBoost builder for resolved GTA V accounts."""

from __future__ import annotations

from typing import Any

from ..models import GtavResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.gameboost import BaseGameBoostBuilder

_STATIC_IMAGE_URL = (
    "https://www.dropbox.com/scl/fi/vp0gnpqlt5g6w12vofuxl/"
    "g-rsel_2025-12-04_085834084.png?rlkey=b84z5cr67r05ykj05yb7eao3e&st=rjxu1pa6&dl=1"
)


class GtavGameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the GTA V account slice."""

    @property
    def game_slug(self) -> str:
        return "grand-theft-auto-v"

    def _build_account_data(self, account: GtavResolvedAccount) -> dict[str, Any]:
        cash_display = f"{account.cash_amount} {account.cash_unit}"
        return {
            "platform": account.main_platform,
            "account_tags": account.tags or [],
            "account_level": account.level or 0,
            "cars_count": account.cars_count or 0,
            "cash_amount": cash_display,
        }

    def build_payload(
        self,
        subject: Any,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        # Override price source: prefer gameboost_price, then price, fallback 500
        original_price = subject.price
        subject.price = subject.gameboost_price or subject.price or 500

        payload = super().build_payload(subject, listing, ctx)

        # Restore original price
        subject.price = original_price

        # Static image URL always
        payload["image_urls"] = [_STATIC_IMAGE_URL]
        return payload

