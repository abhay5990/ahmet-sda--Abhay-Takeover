"""GameBoost builder for resolved GTA V accounts."""

from __future__ import annotations

from typing import Any

from ..credentials import format_platform_credentials
from ..models import GtavResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.enums import ListingKind
from .....marketplaces.base import _DISCLAIMER, _DROPSHIPPING_DELIVERY
from .....marketplaces.gameboost import BaseGameBoostBuilder

_STATIC_IMAGE_URL = (
    "https://www.dropbox.com/scl/fi/vp0gnpqlt5g6w12vofuxl/"
    "g-rsel_2025-12-04_085834084.png?rlkey=b84z5cr67r05ykj05yb7eao3e&st=rjxu1pa6&dl=1"
)

# Canonical platform (UI) -> GameBoost platform value
_PLATFORM_TO_GB: dict[str, str] = {
    "PC - Legacy": "PC · Legacy",
    "PC - Enhanced": "PC · Enhanced",
}


class GtavGameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the GTA V account slice."""

    @property
    def game_slug(self) -> str:
        return "grand-theft-auto-v"

    def _build_account_data(self, account: GtavResolvedAccount) -> dict[str, Any]:
        cash_display = f"{account.cash_amount} {account.cash_unit}"
        gb_platform = _PLATFORM_TO_GB.get(account.main_platform, account.main_platform)
        return {
            "platform": gb_platform,
            "account_tags": account.tags or [],
            "account_level": account.level or 0,
            "cars_count": account.cars_count or 0,
            "cash_amount": cash_display,
            "has_dual_characters": account.has_dual_characters,
        }

    def build_payload(
        self,
        subject: Any,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        payload = super().build_payload(subject, listing, ctx)
        if not payload.get("image_urls"):
            payload["image_urls"] = [_STATIC_IMAGE_URL]

        # Override delivery_instructions with platform-aware credential text
        if ctx.kind == ListingKind.STOCK:
            payload["delivery_instructions"] = format_platform_credentials(
                subject.main_platform,
                subject.credentials,
                subject.credential_extras,
                disclaimer=_DISCLAIMER,
            )
        else:
            payload["delivery_instructions"] = _DROPSHIPPING_DELIVERY

        return payload

