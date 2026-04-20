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
        )
