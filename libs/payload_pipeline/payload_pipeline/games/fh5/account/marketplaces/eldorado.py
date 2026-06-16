"""Eldorado builder for resolved Forza Horizon 5 accounts.

Template reference: ``assets/eldorado_templates/accounts/forza-horizon-5.json``
  - game_id: 106
  - tradeEnvironments: 0=PC, 1=Xbox, 2=PS5
  - attributes: {} (none)
"""

from __future__ import annotations

from ..models import Fh5ResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.variant_mapping import get_external_id
from .....marketplaces.eldorado import BaseEldoradoBuilder


class Fh5EldoradoBuilder(BaseEldoradoBuilder):
    """Eldorado builder for the Forza Horizon 5 account slice."""

    def build_payload(
        self,
        account: Fh5ResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        trade_env = get_external_id(
            ctx.variant_context, "platform", account.platform,
        ) or "0"

        return self.build_base_payload(
            game_id="106",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            trade_environment_id=trade_env,
            ref_key=account.ref_key,
        )
