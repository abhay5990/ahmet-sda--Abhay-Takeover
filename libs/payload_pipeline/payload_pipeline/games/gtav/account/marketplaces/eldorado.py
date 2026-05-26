"""Eldorado builder for resolved GTA V accounts."""

from __future__ import annotations

from ..credentials import format_platform_credentials
from ..models import GtavResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.variant_mapping import get_external_id
from .....marketplaces.eldorado import BaseEldoradoBuilder


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

    @staticmethod
    def _resolve_trade_environment(
        account: GtavResolvedAccount,
        ctx: BuildContext,
    ) -> str:
        return get_external_id(
            ctx.variant_context, "platform", account.main_platform,
        ) or "0"
