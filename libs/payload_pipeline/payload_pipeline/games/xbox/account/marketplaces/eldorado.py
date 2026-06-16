"""Eldorado builder for resolved Xbox accounts.

Template reference: ``assets/eldorado_templates/accounts/xbox.json``
  - game_id: 103
  - tradeEnvironments: [] (none)
  - attributes: {} (none)
"""

from __future__ import annotations

from ..models import XboxResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder


class XboxEldoradoBuilder(BaseEldoradoBuilder):
    """Eldorado builder for the Xbox account slice."""

    def build_payload(
        self,
        account: XboxResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        return self.build_base_payload(
            game_id="103",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            trade_environment_id=None,
            ref_key=account.ref_key,
        )
