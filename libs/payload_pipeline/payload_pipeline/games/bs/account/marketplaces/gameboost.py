"""GameBoost builder for resolved Brawl Stars accounts."""

from __future__ import annotations

from typing import Any

from ..models import BSResolvedAccount
from .....marketplaces.gameboost import BaseGameBoostBuilder


class BSGameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the Brawl Stars account slice."""

    @property
    def game_slug(self) -> str:
        return "brawl-stars"

    @property
    def _platform_name(self) -> str:
        return "Supercell ID"

    def _build_account_data(self, account: BSResolvedAccount, ctx=None) -> dict[str, Any]:
        return {
            "max_level_brawlers_count": account.max_level_brawlers_count,
            "trophies_count": account.trophies,
            "hypercharge_count": 0,
            "experience_level": account.level,
            "gems_count": 0,
            "brawlers_count": account.brawler_count,
            "brawlers_rank_30_plus_count": account.rank_30_plus_count,
            "skins_count": 0,
            "current_rank": None,
            "current_division": None,
        }
