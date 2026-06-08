"""Eldorado builder for resolved R6 accounts."""

from __future__ import annotations

from ..models import R6ResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.variant_mapping import get_external_id
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

_PREVIOUS_RANK_IDS: dict[str, str] = {
    "copper": "previous-copper",
    "bronze": "previous-bronze",
    "silver": "previous-silver",
    "gold": "previous-gold",
    "platinum": "previous-platinum",
    "emerald": "previous-emerald",
    "diamond": "previous-diamond",
    "champion": "previous-champion",
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
            trade_environment_id=self._resolve_trade_environment_id(account, ctx),
            attributes={
                _ATTR_RANK: self._resolve_rank(account),
                _ATTR_BLACK_ICE: self._resolve_black_ice(account.black_ice_count),
                "rainbow-six-game-purchased": "purchased-yes" if account.has_game else "purchased-no",
                "rainbow-six-operators": self._resolve_operators(account.operator_count),
                "rainbow-six-previous-rank": self._resolve_previous_rank(account),
                "rainbow-six-ranked-unlocked": "ranked-unlocked-yes" if account.ranked_ready else "ranked-unlocked-no",
                "rainbow-six-renown": self._resolve_renown(account.renown),
            },
            ref_key=account.ref_key,
        )

    @staticmethod
    def _resolve_trade_environment_id(
        account: R6ResolvedAccount, ctx: BuildContext,
    ) -> str:
        selected = (ctx.selected_variants or {}).get("platform")
        if selected:
            return get_external_id(ctx.variant_context, "platform", selected) or "0"
        # Fallback: map from account field (transition until Phase B)
        return get_external_id(
            ctx.variant_context, "platform", account.primary_linkable_platform,
        ) or "0"

    def _resolve_previous_rank(self, account: R6ResolvedAccount) -> str:
        rank = account.peak_rank.strip().lower()
        if not rank or rank in ("unranked", "no rank"):
            return "previous-other"
        return _PREVIOUS_RANK_IDS.get(rank, "previous-other")

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

    @staticmethod
    def _resolve_operators(count: int) -> str:
        if count <= 9:
            return "operators-09"
        if count <= 14:
            return "operators-1014"
        if count <= 19:
            return "operators-1519"
        if count <= 24:
            return "operators-2024"
        if count <= 29:
            return "operators-2529"
        if count <= 34:
            return "operators-3034"
        if count <= 39:
            return "operators-3539"
        if count <= 44:
            return "operators-4044"
        if count <= 49:
            return "operators-4549"
        return "operators-50plus"

    @staticmethod
    def _resolve_renown(renown: int) -> str:
        if renown <= 5000:
            return "renown-05"
        if renown <= 19000:
            return "renown-619"
        if renown <= 49000:
            return "renown-2049"
        if renown <= 74000:
            return "renown-5074"
        if renown <= 99000:
            return "renown-7599"
        return "renown-100plus"
