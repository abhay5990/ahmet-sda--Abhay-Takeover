"""GameBoost builder for resolved Roblox accounts."""

from __future__ import annotations

from typing import Any

from ..models import RobloxResolvedAccount
from .....marketplaces.gameboost import BaseGameBoostBuilder


class RobloxGameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the Roblox account slice."""

    @property
    def game_slug(self) -> str:
        return "roblox"

    @property
    def _platform_name(self) -> str:
        return "Roblox Account"

    def _build_account_data(self, account: RobloxResolvedAccount) -> dict[str, Any]:
        return {
            "robux_count": account.robux,
        }
