"""Eldorado builder for resolved Forza Horizon 6 accounts.

Template reference: ``assets/eldorado_templates/accounts/forza-horizon-6.json``
  - game_id: 414
  - tradeEnvironments: [] (none)
  - attributes: {} (none)
"""

from __future__ import annotations

from ..models import Fh6ResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder


class Fh6EldoradoBuilder(BaseEldoradoBuilder):
    """Eldorado builder for the Forza Horizon 6 account slice."""

    def build_payload(
        self,
        account: Fh6ResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        return self.build_base_payload(
            game_id="414",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            trade_environment_id=None,
            ref_key=account.ref_key,
        )
