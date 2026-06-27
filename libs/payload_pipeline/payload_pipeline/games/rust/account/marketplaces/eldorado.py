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

        # Prefer integer-derived ranges; fall back to pre-set range IDs.
        hours_attr = (
            self._resolve_hours(account.real_hours)
            if account.real_hours > 0
            else account.hours_range
        )
        skins_attr = (
            self._resolve_skins(account.skins_count)
            if account.skins_count > 0
            else account.skins_range
        )
        steam_level_attr = (
            self._resolve_steam_level(account.steam_level)
            if account.steam_level > 0
            else account.steam_level_range
        )

        attributes = {
            "premium-status": account.premium_status,
            "rust-hours": hours_attr,
            "rust-skins": skins_attr,
            "steam-account-level": steam_level_attr,
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

    @staticmethod
    def _resolve_hours(hours: int) -> str:
        """Map integer hours to Eldorado rust-hours attribute ID."""
        if hours < 100:
            return "hours-099"
        if hours < 500:
            return "hours-100499"
        if hours < 2000:
            return "hours-5001999"
        return "hours-2000"

    @staticmethod
    def _resolve_skins(skins: int) -> str:
        """Map integer skins count to Eldorado rust-skins attribute ID."""
        if skins < 15:
            return "skins-014"
        if skins < 50:
            return "skins-1549"
        if skins < 100:
            return "skins-5099"
        return "skins-100"

    @staticmethod
    def _resolve_steam_level(level: int) -> str:
        """Map integer Steam level to Eldorado steam-account-level attribute ID."""
        if level <= 5:
            return "level-05"
        if level <= 24:
            return "level-624"
        return "level-25"
