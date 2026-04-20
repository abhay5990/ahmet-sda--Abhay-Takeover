"""Eldorado builder for resolved Roblox accounts."""

from __future__ import annotations

from ..models import RobloxResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder


class RobloxEldoradoBuilder(BaseEldoradoBuilder):
    """Foundation Eldorado builder for the Roblox account slice."""

    def build_payload(
        self,
        account: RobloxResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        return self.build_base_payload(
            game_id="70",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
        )
