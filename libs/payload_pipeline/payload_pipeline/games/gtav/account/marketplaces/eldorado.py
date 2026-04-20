"""Eldorado builder for resolved GTA V accounts."""

from __future__ import annotations

from ..models import GtavResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.eldorado import BaseEldoradoBuilder, EldoradoConfig

_PLATFORM_TO_TRADE_ENV = {
    "PC - Legacy": "0",
    "PC - Enhanced": "0",
    "PlayStation 4": "1",
    "PlayStation 5": "3",
    "Xbox One": "2",
    "Xbox Series X/S": "4",
}


class GtavEldoradoBuilder(BaseEldoradoBuilder):
    """Eldorado builder for the GTA V account slice."""

    def build_payload(
        self,
        account: GtavResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict:
        price = account.eldorado_price or account.price or 399
        trade_env = self._resolve_trade_environment(account, ctx)

        payload = self.build_base_payload(
            game_id="25",
            listing=listing,
            ctx=ctx,
            price=price,
            credentials=account.credentials,
            trade_environment_id=trade_env,
        )

        if account.security_email or account.birthday or account.email_backup_codes:
            delivery_lines = self._build_delivery_lines(account)
            payload["accountSecretDetails"] = [delivery_lines]

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

    @staticmethod
    def _build_delivery_lines(account: GtavResolvedAccount) -> str:
        c = account.credentials
        lines = []
        if c.login:
            lines.append(f"Login: {c.login}")
        if c.password:
            lines.append(f"Password: {c.password}")
        if c.email_login:
            lines.append(f"Email: {c.email_login}")
        if c.email_password:
            lines.append(f"Email Password: {c.email_password}")
        if c.email_login_link:
            lines.append(f"Email Login Link: {c.email_login_link}")
        if account.security_email:
            lines.append(f"Security Email: {account.security_email}")
        if account.security_email_password:
            lines.append(f"Security Email Password: {account.security_email_password}")
        if account.security_email_login_link:
            lines.append(f"Security Email Login Link: {account.security_email_login_link}")
        if account.birthday:
            lines.append(f"Birthday: {account.birthday}")
        if account.email_backup_codes:
            lines.append(f"Backup Codes:\n{account.email_backup_codes}")
        return "\n".join(lines)
