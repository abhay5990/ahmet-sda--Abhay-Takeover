"""GameBoost builder for resolved Ubisoft Connect accounts."""

from __future__ import annotations

from typing import Any

from ..models import UbisoftResolvedAccount
from .....marketplaces.gameboost import BaseGameBoostBuilder


class UbisoftGameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the Ubisoft Connect account slice."""

    @property
    def game_slug(self) -> str:
        return "ubisoft-connect"

    @property
    def _platform_name(self) -> str:
        return "Ubisoft Account"

    def _build_account_data(self, account: UbisoftResolvedAccount, ctx=None) -> dict[str, Any]:
        linked_platforms: list[str] = []
        if account.psn_connected:
            linked_platforms.append("PlayStation")
        if account.xbox_connected:
            linked_platforms.append("Xbox")

        return {
            "platform": "PC",
            "linked_platforms": linked_platforms or ["PC"],
            "game_count": account.game_count,
            "country": account.country.upper() if account.country else "",
            "subscription": "Ubisoft+" if account.has_subscription else "",
            "r6_level": account.r6_level,
            "balance": account.converted_balance,
        }
