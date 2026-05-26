"""Eldorado builder for resolved Genshin Impact accounts."""

from __future__ import annotations

from typing import Any

from ..models import GenshinResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.variant_mapping import get_external_id
from .....marketplaces.eldorado import BaseEldoradoBuilder


class GenshinImpactEldoradoBuilder(BaseEldoradoBuilder):
    """Eldorado payload builder for the Genshin Impact account slice."""

    def build_payload(
        self,
        account: GenshinResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        trade_env = get_external_id(
            ctx.variant_context, "region", account.region.lower(),
        ) or "1-999"

        return self.build_base_payload(
            game_id="39",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            trade_environment_id=trade_env,
            ref_key=account.ref_key,
        )
