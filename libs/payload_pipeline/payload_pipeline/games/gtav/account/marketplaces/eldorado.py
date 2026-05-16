"""Eldorado builder for resolved GTA V accounts."""

from __future__ import annotations

from ..credentials import format_platform_credentials
from ..models import GtavResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder, EldoradoConfig

_PLATFORM_TO_TRADE_ENV = {
    "PC - Legacy": "0",
    "PlayStation 4": "1",
    "Xbox One": "2",
    "PlayStation 5": "3",
    "Xbox Series X/S": "4",
    "PC - Enhanced": "5",
}


class GtavEldoradoBuilder(BaseEldoradoBuilder):
    """Eldorado builder for the GTA V account slice."""

    def build_payload(
        self,
        account: GtavResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        trade_env = self._resolve_trade_environment(account, ctx)

        payload = self.build_base_payload(
            game_id="25",
            listing=listing,
            ctx=ctx,
            price=account.price,
            credentials=account.credentials,
            trade_environment_id=trade_env,
            ref_key=account.ref_key,
        )

        delivery = format_platform_credentials(
            account.main_platform,
            account.credentials,
            account.credential_extras,
        )
        if delivery:
            if account.email_backup_codes:
                delivery += f"\nBackup Codes:\n{account.email_backup_codes}"
            payload["accountSecretDetails"] = [delivery]

        return payload

    def _resolve_trade_environment(
        self,
        account: GtavResolvedAccount,
        ctx: BuildContext,
    ) -> str:
        el_config = ctx.get_config(EldoradoConfig)
        manual = el_config.current_subplatform
        if manual and manual != "Auto":
            return _PLATFORM_TO_TRADE_ENV.get(manual, "0")
        return _PLATFORM_TO_TRADE_ENV.get(account.main_platform, "0")
