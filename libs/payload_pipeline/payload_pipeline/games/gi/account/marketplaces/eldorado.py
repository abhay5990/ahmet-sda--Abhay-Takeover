"""Eldorado builder for resolved Genshin Impact accounts."""

from __future__ import annotations

from typing import Any

from ..models import GenshinResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder


_REGION_TRADE_ENV: dict[str, str] = {
    "na": "0",
    "eu": "1",
    "asia": "2",
    "tw": "3",
}


class GenshinImpactEldoradoBuilder(BaseEldoradoBuilder):
    """Eldorado payload builder for the Genshin Impact account slice."""

    def build_payload(
        self,
        account: GenshinResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        return self.build_base_payload(
            game_id="39",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            trade_environment_id=_REGION_TRADE_ENV.get(
                account.region.lower(), "1-999"
            ),
        )
