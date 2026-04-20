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
        )
