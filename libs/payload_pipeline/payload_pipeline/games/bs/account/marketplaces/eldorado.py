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
                "brawl-stars-rank": "rank-other",
                "brawl-stars-trophies": self._resolve_trophies(account.trophies),
                "brawl-stars-prestige": "prestige-other",
                "brawl-stars-brawlers": self._resolve_brawlers(account.brawler_count),
                "brawl-stars-maxed-brawlers": self._resolve_maxed_brawlers(account.max_level_brawlers_count),
                "brawl-stars-skins": "skins-other",
                "brawl-stars-hypercharge": "hypercharge-other",
                "brawl-stars-buffies": "buffies-other",
                "brawl-gemss": "gems-other",
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
