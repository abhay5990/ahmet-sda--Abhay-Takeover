"""GameBoost builder for resolved Clash of Clans accounts."""

from __future__ import annotations

from typing import Any

from ..models import CocResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.gameboost import BaseGameBoostBuilder


_DEFAULT_IMAGE_URL = (
    "https://www.dropbox.com/scl/fi/1fbqzbc28e7zk1i6pg7lu/"
    "resim_2025-10-09_185629122.png?rlkey=dumfe71gkhikujewtxjuzcqrv&st=6dk3oh6i&dl=1"
)


class CocGameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the Clash of Clans account slice."""

    @property
    def game_slug(self) -> str:
        return "clash-of-clans"

    @property
    def _platform_name(self) -> str:
        return "Supercell ID"

    def _build_account_data(self, account: CocResolvedAccount, ctx=None) -> dict[str, Any]:
        return {
            "clan_role": None,
            "town_hall_level": account.town_hall_level,
            "experience_level": account.account_level,
            "gems_count": 0,
            "minion_prince_level": 0,
            "barbarian_king_level": account.barbarian_king_level,
            "archer_queen_level": account.archer_queen_level,
            "grand_warden_level": account.grand_warden_level,
            "royal_champion_level": account.royal_champion_level,
            "trophy_count": account.trophies,
            "builder_hall_level": max(1, account.builder_hall_level),
            "battle_machine_level": 0,
            "clan_level": 0,
            "max": False,
        }

    def build_payload(
        self,
        subject: Any,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        payload = super().build_payload(subject, listing, ctx)
        if not payload["image_urls"]:
            payload["image_urls"] = [_DEFAULT_IMAGE_URL]
        return payload
