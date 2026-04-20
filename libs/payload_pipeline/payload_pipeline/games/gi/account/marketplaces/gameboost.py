"""GameBoost builder for resolved Genshin Impact accounts."""

from __future__ import annotations

from typing import Any

from ..models import GenshinResolvedAccount
from .....marketplaces.gameboost import BaseGameBoostBuilder


_REGION_SERVER: dict[str, str] = {
    "na": "America",
    "eu": "Europe",
    "asia": "Asia",
    "tw": "TW/HK/MO",
}


class GenshinImpactGameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the Genshin Impact account slice."""

    @property
    def game_slug(self) -> str:
        return "genshin-impact"

    @property
    def _platform_name(self) -> str:
        return "miHoYo Account"

    def _build_account_data(self, account: GenshinResolvedAccount) -> dict[str, Any]:
        data: dict[str, Any] = {
            "server": _REGION_SERVER.get(account.region.lower(), "Europe"),
            "adventure_rank": account.genshin_level,
            "platforms": ["PC", "PlayStation", "Xbox", "Android", "iOS", "Switch"],
            "email_not_linked": not account.has_email_access,
        }
        if account.genshin_currency:
            data["primogems_count"] = account.genshin_currency
        return data

