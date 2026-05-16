"""Eldorado builder for resolved Clash Royale accounts."""

from __future__ import annotations

from ..models import CrResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder


class CrEldoradoBuilder(BaseEldoradoBuilder):
    """Foundation Eldorado builder for the Clash Royale account slice."""

    def build_payload(
        self,
        account: CrResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        return self.build_base_payload(
            game_id="52",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            ref_key=account.ref_key,
        )
