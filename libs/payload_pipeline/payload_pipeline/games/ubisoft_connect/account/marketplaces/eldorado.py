"""Eldorado builder for resolved Ubisoft Connect accounts."""

from __future__ import annotations

from ..models import UbisoftResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder


class UbisoftEldoradoBuilder(BaseEldoradoBuilder):
    """Build Eldorado payloads for the Ubisoft Connect account slice.

    Eldorado game ID 65.  Ubisoft accounts are not region-segmented on
    Eldorado so no trade environment or attribute bucketing is applied.
    """

    def build_payload(
        self,
        account: UbisoftResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        return self.build_base_payload(
            game_id="65",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            ref_key=account.ref_key,
        )
