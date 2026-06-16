"""Eldorado builder for resolved PSN accounts.

Template reference: ``assets/eldorado_templates/accounts/psn.json``
  - game_id: 104
  - tradeEnvironments: [] (none)
  - attributes: {} (none)
"""

from __future__ import annotations

from ..models import PsnResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder


class PsnEldoradoBuilder(BaseEldoradoBuilder):
    """Eldorado builder for the PSN account slice."""

    def build_payload(
        self,
        account: PsnResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        return self.build_base_payload(
            game_id="104",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            trade_environment_id=None,
            ref_key=account.ref_key,
        )
