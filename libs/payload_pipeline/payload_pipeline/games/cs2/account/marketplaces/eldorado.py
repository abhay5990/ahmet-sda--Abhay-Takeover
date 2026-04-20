"""Eldorado builder for resolved CS2 accounts."""

from __future__ import annotations

from ..models import CS2ResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder


class CS2EldoradoBuilder(BaseEldoradoBuilder):
    """Foundation Eldorado builder for the CS2 slice."""

    def build_payload(
        self,
        account: CS2ResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        return self.build_base_payload(
            game_id="20",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            trade_environment_id=self._resolve_trade_environment_id(account.premier_elo),
            attributes={
                "counter-strike-2-prime-status": "active-prime" if account.is_prime else "non-prime",
                "counter-strike-2-medals": self._medal_bucket(account.medal_count),
            },
        )

    @staticmethod
    def _medal_bucket(count: int) -> str:
        if count <= 9:
            return "0-9-medals"
        if count <= 19:
            return "10-19-medals"
        if count <= 29:
            return "20-29-medals"
        if count <= 39:
            return "30-39-medals"
        return "40+-medals"

    def _resolve_trade_environment_id(self, premier_elo: int) -> str:
        if premier_elo <= 0:
            return "0"
        if premier_elo < 5000:
            return "1"
        if premier_elo < 10000:
            return "2"
        if premier_elo < 15000:
            return "3"
        if premier_elo < 20000:
            return "4"
        if premier_elo < 25000:
            return "5"
        if premier_elo < 30000:
            return "6"
        if premier_elo < 35000:
            return "7"
        return "8"
