"""Eldorado builder for resolved League of Legends accounts."""

from __future__ import annotations

from ..models import LolResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.variant_mapping import get_external_id
from .....marketplaces.eldorado import BaseEldoradoBuilder

# Eldorado semantic attribute keys (from template)
_ATTR_RANK = "lol-current-rank"
_ATTR_SKINS = "lol-skins"
_ATTR_BLUE_ESSENCE = "lol-blue-essence"

_RANK_ATTRIBUTE_IDS: dict[str, str] = {
    "iron": "iron",
    "bronze": "bronze",
    "silver": "silver",
    "gold": "gold",
    "platinum": "platinum",
    "emerald": "emerald",
    "diamond": "diamond",
    "master": "other",
    "grandmaster": "other",
    "challenger": "other",
}


class LolEldoradoBuilder(BaseEldoradoBuilder):
    """Eldorado builder for the League of Legends account slice."""

    def build_payload(
        self,
        account: LolResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        return self.build_base_payload(
            game_id="17",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            trade_environment_id=self._resolve_trade_environment_id(
                account.region_phrase, ctx,
            ),
            attributes={
                _ATTR_RANK: self._resolve_rank_attribute(account.rank),
                _ATTR_SKINS: self._resolve_skin_attribute(account.skin_count),
                _ATTR_BLUE_ESSENCE: self._resolve_blue_essence_attribute(account.blue_essence),
                "league-of-legends-champion-count": self._resolve_champion_count(account.champion_count),
                "league-of-legends-previous-rank": "previous-unranked",
                "league-of-legends-ranked-ready": "ready-yes" if account.level >= 30 else "ready-no",
                "league-of-legends-riot-points": self._resolve_riot_points(account.riot_points),
            },
            ref_key=account.ref_key,
        )

    @staticmethod
    def _resolve_trade_environment_id(region_phrase: str, ctx: BuildContext) -> str:
        return get_external_id(ctx.variant_context, "region", region_phrase) or "0"

    @staticmethod
    def _resolve_rank_attribute(rank: str) -> str:
        if not rank:
            return "unranked"
        first_token = rank.split()[0].strip().lower()
        return _RANK_ATTRIBUTE_IDS.get(first_token, "unranked")

    @staticmethod
    def _resolve_skin_attribute(skin_count: int) -> str:
        if skin_count == 0:
            return "0-skins"
        if skin_count <= 9:
            return "1-9-skins"
        if skin_count <= 24:
            return "10-24-skins"
        if skin_count <= 49:
            return "25-49-skins"
        if skin_count <= 99:
            return "50-99-skins"
        if skin_count <= 199:
            return "100-199-skins"
        if skin_count <= 299:
            return "200-299-skins"
        if skin_count <= 399:
            return "300-399-skins"
        if skin_count <= 499:
            return "400-499-skins"
        if skin_count <= 699:
            return "500-699-skins"
        if skin_count <= 899:
            return "700-899-skins"
        if skin_count <= 1099:
            return "900-1099-skins"
        if skin_count <= 1399:
            return "1100-1399-skins"
        return "1400-plus-skins"

    @staticmethod
    def _resolve_blue_essence_attribute(blue_essence: int) -> str:
        if blue_essence <= 19000:
            return "0-19k-be"
        if blue_essence <= 40000:
            return "20-40k-be"
        if blue_essence <= 60000:
            return "41-60k-be"
        if blue_essence <= 80000:
            return "61-80k-be"
        if blue_essence <= 100000:
            return "81-100k-be"
        return "100k-plus-be"

    @staticmethod
    def _resolve_champion_count(champion_count: int) -> str:
        if champion_count <= 19:
            return "champion-119"
        if champion_count <= 49:
            return "champion-2049"
        if champion_count <= 79:
            return "champion-5079"
        if champion_count <= 119:
            return "champion-80119"
        if champion_count >= 120:
            return "champion-120plus"
        return "champion-other"

    @staticmethod
    def _resolve_riot_points(riot_points: int) -> str:
        if riot_points <= 0:
            return "riot-other"
        if riot_points <= 999:
            return "riot-999"
        if riot_points <= 3999:
            return "riot-1399"
        if riot_points <= 9999:
            return "riot-4999"
        if riot_points <= 19999:
            return "riot-101999"
        return "riot-20plus"
