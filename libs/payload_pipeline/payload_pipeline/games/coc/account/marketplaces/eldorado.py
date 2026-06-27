"""Eldorado builder for resolved Clash of Clans accounts."""

from __future__ import annotations

from ..models import CocResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder


class CocEldoradoBuilder(BaseEldoradoBuilder):
    """Foundation Eldorado builder for the Clash of Clans account slice."""

    def build_payload(
        self,
        account: CocResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        return self.build_base_payload(
            game_id="18",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            attributes={
                "clash-of-clans-current-rank": account.current_rank_attr or self._resolve_rank(account.trophies),
                "clash-of-clans-maxed-account": account.maxed_account_attr or ("maxed-yes" if account.town_hall_level >= 18 else "maxed-no"),
                "clash-of-clans-town-hall": self._resolve_town_hall(account.town_hall_level),
                "coc-gems": self._resolve_gems(account.gems_count),
            },
            ref_key=account.ref_key,
        )

    # ── attribute resolvers ──────────────────────────────────────

    @staticmethod
    def _resolve_rank(trophies: int) -> str:
        if trophies <= 0:
            return "rank-unranked"
        if trophies < 500:
            return "rank-skeleton"
        if trophies < 1000:
            return "rank-barbarian"
        if trophies < 1500:
            return "rank-archer"
        if trophies < 2000:
            return "rank-wizard"
        if trophies < 2500:
            return "rank-valkyrie"
        if trophies < 3000:
            return "rank-witch"
        if trophies < 3500:
            return "rank-golem"
        if trophies < 4000:
            return "rank-pekka"
        if trophies < 4500:
            return "rank-titan"
        if trophies < 5000:
            return "rank-dragon"
        if trophies < 5500:
            return "rank-electro"
        return "rank-legend"

    @staticmethod
    def _resolve_town_hall(level: int) -> str:
        if level <= 3:
            return "hall-13"
        if level <= 6:
            return "hall-46"
        if level <= 9:
            return "hall-79"
        if level <= 12:
            return "hall-1012"
        if level <= 15:
            return "hall-1315"
        if level <= 17:
            return "hall-1617"
        if level >= 18:
            return "hall-18"
        return "hall-other"

    @staticmethod
    def _resolve_gems(count: int) -> str:
        if count <= 0:
            return "gems-other"
        if count <= 499:
            return "gems-0499"
        if count <= 999:
            return "gems-500999"
        if count <= 2499:
            return "gems-1249"
        if count <= 4999:
            return "gems-25499"
        if count <= 9999:
            return "gems-5999"
        if count <= 24999:
            return "gems-102499"
        return "gems-25plus"
