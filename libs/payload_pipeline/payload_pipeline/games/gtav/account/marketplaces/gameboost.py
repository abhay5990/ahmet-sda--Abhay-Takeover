"""GameBoost builder for resolved GTA V accounts."""

from __future__ import annotations

from typing import Any

from ..credentials import format_platform_credentials
from ..models import GtavResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.enums import ListingKind
from .....core.variant_mapping import get_external_id
from .....marketplaces.base import _DISCLAIMER, _DROPSHIPPING_DELIVERY
from .....marketplaces.gameboost import BaseGameBoostBuilder

_STATIC_IMAGE_URL = (
    "https://www.dropbox.com/scl/fi/vp0gnpqlt5g6w12vofuxl/"
    "g-rsel_2025-12-04_085834084.png?rlkey=b84z5cr67r05ykj05yb7eao3e&st=rjxu1pa6&dl=1"
)

# Maps internal account tags to Gameboost-valid enum values.
# Tags not present here are silently dropped — Gameboost rejects unknown values.
_GAMEBOOST_TAG_MAP: dict[str, str] = {
    "high level": "High Level Account",
    "high level account": "High Level Account",
    "billionaire": "Billionaire Account",
    "billionaire account": "Billionaire Account",
    "rare": "Rare Account",
    "rare account": "Rare Account",
    "starter": "Starter Account",
    "starter account": "Starter Account",
}


def _map_tags(tags: list[str]) -> list[str]:
    """Convert internal tags to Gameboost-valid values, dropping unknowns."""
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        mapped = _GAMEBOOST_TAG_MAP.get(tag.lower())
        if mapped and mapped not in seen:
            seen.add(mapped)
            result.append(mapped)
    return result


class GtavGameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the GTA V account slice."""

    @property
    def game_slug(self) -> str:
        return "grand-theft-auto-v"

    def _build_account_data(
        self, account: GtavResolvedAccount, ctx: BuildContext | None = None,
    ) -> dict[str, Any]:
        cash_display = f"{account.cash_amount} {account.cash_unit}"
        gb_platform = get_external_id(
            ctx.variant_context if ctx else None, "platform", account.main_platform,
        ) or account.main_platform
        return {
            "platform": gb_platform,
            "account_tags": _map_tags(account.tags or []),
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

