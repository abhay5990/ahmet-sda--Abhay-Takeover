"""GameBoost builder for resolved Genshin Impact accounts."""

from __future__ import annotations

from typing import Any

from ..models import GenshinResolvedAccount
from .....core.contracts import BuildContext
from .....core.variant_mapping import get_external_id
from .....marketplaces.gameboost import BaseGameBoostBuilder


class GenshinImpactGameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the Genshin Impact account slice."""

    @property
    def game_slug(self) -> str:
        return "genshin-impact"

    @property
    def _platform_name(self) -> str:
        return "miHoYo Account"

    def _build_account_data(
        self, account: GenshinResolvedAccount, ctx: BuildContext | None = None,
    ) -> dict[str, Any]:
        region = account.region.lower()
        server = get_external_id(
            ctx.variant_context if ctx else None, "region", region,
        ) or "Europe"
        data: dict[str, Any] = {
            "server": server,
            "adventure_rank": account.genshin_level,
            "platforms": ["PC", "PlayStation", "Xbox", "Android", "iOS", "Switch"],
            "email_not_linked": not account.has_email_access,
        }
        if account.genshin_currency:
            data["primogems_count"] = account.genshin_currency
        return data

