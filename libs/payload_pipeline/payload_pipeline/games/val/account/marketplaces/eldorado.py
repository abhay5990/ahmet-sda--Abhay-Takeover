"""Eldorado builder for resolved Valorant accounts."""

from __future__ import annotations

from ..models import ValorantResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder, EldoradoConfig
from .subplatform import resolve_platform_id


_REGION_IDS = {
    "NA": "0",
    "EU": "1",
    "LA": "2",
    "BR": "3",
    "AP": "5",
    "KR": "6",
}

# Eldorado attribute keys & value IDs (from template)
_ATTR_RANK = "valorant-rank"
_ATTR_AGENTS = "valorant-agents"
_ATTR_SKINS = "valorant-weapon-skins"

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
            },
            ref_key=account.ref_key,
        )

    def _resolve_trade_environment_id(
        self, region: str, ctx: BuildContext,
    ) -> str:
        region_id = _REGION_IDS.get(region.upper(), "1-999")
        if region_id == "1-999":
            return region_id

        el_config = ctx.get_config(EldoradoConfig)
        platform_id = resolve_platform_id(
            manual_selection=el_config.current_subplatform,
            subplatform_status=el_config.subplatform_status,
        )
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
        return "20-plus-agents"

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
