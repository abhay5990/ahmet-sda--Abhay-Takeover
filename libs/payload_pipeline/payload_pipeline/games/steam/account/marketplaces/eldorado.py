"""Eldorado builder for resolved Steam accounts."""

from __future__ import annotations

from ..models import SteamResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder


class SteamEldoradoBuilder(BaseEldoradoBuilder):
    """Foundation Eldorado builder for the Steam account slice."""

    def build_payload(
        self,
        account: SteamResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        return self.build_base_payload(
            game_id="42",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
        )
