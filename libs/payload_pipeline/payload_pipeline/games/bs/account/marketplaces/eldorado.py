"""Eldorado builder for resolved Brawl Stars accounts."""

from __future__ import annotations

from ..models import BSResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder


class BSEldoradoBuilder(BaseEldoradoBuilder):
    """Foundation Eldorado builder for the Brawl Stars account slice."""

    def build_payload(
        self,
        account: BSResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        return self.build_base_payload(
            game_id="56",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            attributes={
                "brawl-stars-rank": account.rank_attr or "rank-other",
                "brawl-stars-trophies": self._resolve_trophies(account.trophies),
                "brawl-stars-prestige": self._resolve_prestige(account.prestige_count),
                "brawl-stars-brawlers": self._resolve_brawlers(account.brawler_count),
                "brawl-stars-maxed-brawlers": self._resolve_maxed_brawlers(account.max_level_brawlers_count),
                "brawl-stars-skins": self._resolve_skins(account.skin_count),
                "brawl-stars-hypercharge": self._resolve_hypercharge(account.hypercharge_count),
                "brawl-stars-buffies": self._resolve_buffies(account.buffies_count),
                "brawl-gemss": self._resolve_gems(account.gems_count),
            },
            ref_key=account.ref_key,
        )

    @staticmethod
    def _resolve_trophies(trophies: int) -> str:
        if trophies <= 9999:
            return "trophies-09k"
        if trophies <= 19999:
            return "trophies-1019k"
        if trophies <= 29999:
            return "trophies-2029k"
        if trophies <= 39999:
            return "trophies-3039k"
        if trophies <= 49999:
            return "trophies-4049k"
        if trophies <= 59999:
            return "trophies-5059k"
        if trophies <= 69999:
            return "trophies-6069k"
        if trophies <= 79999:
            return "trophies-7079k"
        if trophies <= 89999:
            return "trophies-8089k"
        if trophies <= 99999:
            return "trophies-9099k"
        return "trophies-100kplus"

    @staticmethod
    def _resolve_brawlers(count: int) -> str:
        if count <= 19:
            return "brawlers-019"
        if count <= 39:
            return "brawlers-2039"
        if count <= 59:
            return "brawlers-4059"
        if count <= 79:
            return "brawlers-6079"
        if count <= 99:
            return "brawlers-8099"
        return "brawlers-100plus"

    @staticmethod
    def _resolve_maxed_brawlers(count: int) -> str:
        if count <= 19:
            return "maxed-019"
        if count <= 39:
            return "maxed-2039"
        if count <= 59:
            return "maxed-4059"
        if count <= 79:
            return "maxed-6079"
        if count <= 99:
            return "maxed-8099"
        return "maxed-100plus"

    @staticmethod
    def _resolve_hypercharge(count: int) -> str:
        if count <= 19:
            return "hypercharge-019"
        if count <= 39:
            return "hypercharge-2039"
        if count <= 59:
            return "hypercharge-4059"
        if count <= 79:
            return "hypercharge-6079"
        if count <= 99:
            return "hypercharge-8099"
        return "hypercharge-100plus"

    @staticmethod
    def _resolve_skins(count: int) -> str:
        if count <= 0:
            return "skins-other"
        if count <= 99:
            return "skins-099"
        if count <= 199:
            return "skins-100199"
        if count <= 299:
            return "skins-200299"
        if count <= 399:
            return "skins-300399"
        if count <= 499:
            return "skins-400499"
        if count <= 599:
            return "skins-500599"
        return "skins-600plus"

    @staticmethod
    def _resolve_prestige(count: int) -> str:
        if count <= 0:
            return "prestige-other"
        if count <= 24:
            return "prestige-024"
        if count <= 49:
            return "prestige-2549"
        if count <= 99:
            return "prestige-5099"
        if count <= 149:
            return "prestige-100149"
        if count <= 199:
            return "prestige-150199"
        return "prestige-200plus"

    @staticmethod
    def _resolve_buffies(count: int) -> str:
        if count <= 0:
            return "buffies-other"
        if count <= 19:
            return "buffies-019"
        if count <= 39:
            return "buffies-2039"
        if count <= 59:
            return "buffies-4059"
        return "buffies-60plus"

    @staticmethod
    def _resolve_gems(count: int) -> str:
        if count <= 0:
            return "gems-other"
        if count <= 49:
            return "gems-049"
        if count <= 99:
            return "gems-5099"
        if count <= 499:
            return "gems-100499"
        if count <= 999:
            return "gems-500999"
        return "gems-1000plus"
