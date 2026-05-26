"""GameBoost builder for resolved Steam accounts."""

from __future__ import annotations

from typing import Any

from ..models import SteamResolvedAccount
from .....marketplaces.gameboost import BaseGameBoostBuilder


class SteamGameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the Steam account slice."""

    @property
    def game_slug(self) -> str:
        return "steam"

    @property
    def _platform_name(self) -> str:
        return "Steam Account"

    def _build_account_data(self, account: SteamResolvedAccount, ctx=None) -> dict[str, Any]:
        return {
            "platform": "PC",
            "steam_level": account.steam_level,
            "games_count": account.total_games,
            "country": account.country.upper() if account.country else "",
        }
