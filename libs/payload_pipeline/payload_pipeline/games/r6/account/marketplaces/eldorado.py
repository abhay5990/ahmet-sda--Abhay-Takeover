"""Eldorado builder for resolved R6 accounts."""

from __future__ import annotations

from ..models import R6ResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder

# Eldorado attribute keys & value IDs (from template)
_ATTR_RANK = "rainbow-six-siege-x-current-rank"
_ATTR_BLACK_ICE = "rainbow-six-siege-x-black-ice-skins"

_RANK_IDS: dict[str, str] = {
    "copper": "copper",
    "bronze": "bronze",
    "silver": "silver",
    "gold": "gold",
    "platinum": "platinum",
    "emerald": "emerald",
    "diamond": "diamond",
    "champions": "champions",
}


class R6EldoradoBuilder(BaseEldoradoBuilder):
    """Foundation Eldorado builder for the R6 slice."""

    def build_payload(
        self,
        account: R6ResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        price = account.price if not account.use_fixed_price else max(account.price, 0.1)
        return self.build_base_payload(
            game_id="48",
            listing=listing,
            ctx=ctx,
            price=price,
            credentials=account.credentials,
            trade_environment_id=self._resolve_trade_environment_id(account),
            attributes={
                _ATTR_RANK: self._resolve_rank(account),
                _ATTR_BLACK_ICE: self._resolve_black_ice(account.black_ice_count),
            },
        )

    def _resolve_trade_environment_id(self, account: R6ResolvedAccount) -> str:
        if account.platform_flags.get("psn"):
            return "1"
        if account.platform_flags.get("xbox"):
            return "2"
        return "0"

    def _resolve_rank(self, account: R6ResolvedAccount) -> str:
        rank = account.current_rank.strip().lower()
        if not rank or rank in ("unranked", "no rank"):
            return "ranked-ready" if account.ranked_ready else "other"
        return _RANK_IDS.get(rank, "other")

    @staticmethod
    def _resolve_black_ice(count: int) -> str:
        if count == 0:
            return "0"
        if count >= 50:
            return "50"
        if count <= 4:
            return "1-4"
        if count <= 9:
            return "5-9"
        if count <= 19:
            return "10-19"
        if count <= 29:
            return "20-29"
        if count <= 39:
            return "30-39"
        return "40-49"
