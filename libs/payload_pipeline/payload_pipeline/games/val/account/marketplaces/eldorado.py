"""Eldorado builder for resolved Valorant accounts."""

from __future__ import annotations

from ..models import ValorantResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.variant_mapping import get_external_id
from .....marketplaces.eldorado import BaseEldoradoBuilder

# Eldorado attribute keys & value IDs (from template)
_ATTR_RANK = "valorant-rank"
_ATTR_AGENTS = "valorant-agents"
_ATTR_SKINS = "valorant-weapon-skins"
_ATTR_KNIVES = "valorant-knives"
_ATTR_SPENT = "valorant-spent-points"

_REGION_ID_FALLBACKS: dict[str, str] = {
    "na": "0",
    "eu": "1",
    "la": "2",
    "latam": "2",
    "br": "3",
    "ap": "5",
    "apac": "5",
    "kr": "6",
    "tr": "1",
    "turkey": "1",
}

_RANK_IDS: dict[str, str] = {
    "iron": "iron",
    "bronze": "bronze",
    "silver": "silver",
    "gold": "gold",
    "platinum": "platinum",
    "diamond": "diamond",
    "ascendant": "ascendant",
    "immortal": "immortal",
    "radiant": "radiant",
}


class ValorantEldoradoBuilder(BaseEldoradoBuilder):
    """Foundation Eldorado builder for the Valorant account slice."""

    def build_payload(
        self,
        account: ValorantResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        return self.build_base_payload(
            game_id="32",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            trade_environment_id=self._resolve_trade_environment_id(
                account.region, ctx,
            ),
            attributes={
                _ATTR_RANK: self._resolve_rank(account),
                _ATTR_AGENTS: self._resolve_agents(account.agent_count),
                _ATTR_SKINS: self._resolve_skins(account.skin_count),
                _ATTR_KNIVES: self._resolve_knives(account.knife_count),
                _ATTR_SPENT: self._resolve_spent_points(account.inventory_value),
            },
            ref_key=account.ref_key,
        )

    @staticmethod
    def _resolve_trade_environment_id(region: str, ctx: BuildContext) -> str:
        """Build composite trade_env_id: ``"{region_id}-{platform_id}"``."""
        region_key = str(region or "").strip()
        region_id = get_external_id(
            ctx.variant_context, "region", region_key.upper(),
        ) or _REGION_ID_FALLBACKS.get(region_key.lower()) or "1-999"
        if region_id == "1-999":
            return region_id

        platform_slug = (ctx.selected_variants or {}).get("platform")
        platform_id = get_external_id(
            ctx.variant_context, "platform", platform_slug,
        ) or "0"
        return f"{region_id}-{platform_id}"

    def _resolve_rank(self, account: ValorantResolvedAccount) -> str:
        rank_type = account.rank_type.lower()

        # Expired rank → site attribute'una güncel durumu yansıt
        if rank_type != "ranked":
            return "ranked-ready" if account.level >= 20 else "unranked"

        first_token = str(account.current_rank or "").split(" ", 1)[0].strip().lower()
        if not first_token or first_token in ("unranked", "no", "unrated"):
            return "ranked-ready" if account.level >= 20 else "unranked"
        return _RANK_IDS.get(first_token, "other")

    @staticmethod
    def _resolve_agents(agent_count: int) -> str:
        if agent_count <= 5:
            return "0-5-agents"
        if agent_count <= 10:
            return "6-10-agents"
        if agent_count <= 15:
            return "11-15-agents"
        if agent_count <= 20:
            return "16-20-agents"
        if agent_count <= 25:
            return "agents-2125"
        return "agents-26plus"

    @staticmethod
    def _resolve_skins(skin_count: int) -> str:
        if skin_count == 0:
            return "0-skins"
        if skin_count <= 9:
            return "1-9-skins"
        if skin_count <= 19:
            return "10-19-skins"
        if skin_count <= 39:
            return "20-39-skins"
        if skin_count <= 69:
            return "40-69-skins"
        if skin_count <= 99:
            return "70-99-skins"
        return "100-plus-skins"

    @staticmethod
    def _resolve_knives(knife_count: int) -> str:
        if knife_count == 0:
            return "knives-0"
        if knife_count <= 4:
            return "knives-04"
        if knife_count <= 9:
            return "knives-59"
        if knife_count <= 14:
            return "knives-1014"
        if knife_count <= 19:
            return "knives-1519"
        return "knives-20plus"

    @staticmethod
    def _resolve_spent_points(inventory_value: int) -> str:
        if inventory_value < 5000:
            return "spent-0499"
        if inventory_value < 10000:
            return "spent-5999"
        if inventory_value < 20000:
            return "spent-101999"
        if inventory_value < 35000:
            return "spent-203499"
        return "spent-35plus"
