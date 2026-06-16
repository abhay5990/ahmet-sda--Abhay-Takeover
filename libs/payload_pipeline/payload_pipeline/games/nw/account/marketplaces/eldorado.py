"""Eldorado builder for resolved New World accounts.

Template reference: ``assets/eldorado_templates/accounts/new-world.json``
  - game_id: 36
  - tradeEnvironments: 0=US-East, 1=US-West, 2=AP Southeast, 3=SA East, 4=EU-Central
  - attributes: {} (none)
"""

from __future__ import annotations

from ..models import NwResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.variant_mapping import get_external_id
from .....marketplaces.eldorado import BaseEldoradoBuilder


class NwEldoradoBuilder(BaseEldoradoBuilder):
    """Eldorado builder for the New World account slice."""

    def build_payload(
        self,
        account: NwResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        trade_env = get_external_id(
            ctx.variant_context, "region", account.region,
        ) or "0"

        return self.build_base_payload(
            game_id="36",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            trade_environment_id=trade_env,
            ref_key=account.ref_key,
        )
