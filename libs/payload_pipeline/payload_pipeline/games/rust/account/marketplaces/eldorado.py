"""Eldorado builder for resolved Rust accounts.

Template reference: ``assets/eldorado_templates/accounts/rust.json``
  - game_id: 37
  - tradeEnvironments: 0=PC, 1=PlayStation, 2=Xbox
  - attributes:
      premium-status: premium-yes | premium-no | premium-other
      rust-hours:     hours-099 | hours-100499 | hours-5001999 | hours-2000 | hours-other
      rust-skins:     skins-014 | skins-1549 | skins-5099 | skins-100 | skins-other
      steam-account-level: level-05 | level-624 | level-25 | level-other
"""

from __future__ import annotations

from ..models import RustResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.variant_mapping import get_external_id
from .....marketplaces.eldorado import BaseEldoradoBuilder


class RustEldoradoBuilder(BaseEldoradoBuilder):
    """Eldorado builder for the Rust account slice."""

    def build_payload(
        self,
        account: RustResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        trade_env = get_external_id(
            ctx.variant_context, "platform", account.platform,
        ) or "0"

        attributes = {
            "premium-status": account.premium_status,
            "rust-hours": account.hours_range,
            "rust-skins": account.skins_range,
            "steam-account-level": account.steam_level_range,
        }

        return self.build_base_payload(
            game_id="37",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            trade_environment_id=trade_env,
            attributes=attributes,
            ref_key=account.ref_key,
        )
