"""PlayerAuctions builder for resolved Forza Horizon 6 accounts.

Verified with the public seller creation target and an authenticated read-only
account-server lookup on 2026-10-01:
- game_id: 15127
- servers: PC (15128), PS (15129), Xbox (15130)
"""

from __future__ import annotations

from typing import Any

from ..models import Fh6ResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.variant_mapping import get_external_id, get_external_name
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_FALLBACK_SERVER = "PC"
_FALLBACK_SERVER_ID = "15128"


class Fh6PlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the Forza Horizon 6 account slice."""

    @property
    def game_name(self) -> str:
        return "forza-horizon-6"

    @property
    def _pa_game_display_name(self) -> str:
        return "Forza Horizon 6"

    @property
    def game_id(self) -> int:
        return 15127

    @property
    def cover_image_url(self) -> str:
        # The base builder does not transmit a cover image. Keep this empty until
        # a seller-template metadata endpoint supplies an official asset URL.
        return ""

    @property
    def _platform_name(self) -> str:
        return "Forza Horizon 6 Account"

    def _get_server(
        self, account: Fh6ResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str]:
        name = get_external_name(
            ctx.variant_context if ctx else None, "platform", account.platform,
        )
        return [name or {"PS5": "PS", "Xbox": "XBOX"}.get(account.platform, _FALLBACK_SERVER)]

    def _get_server_id(
        self, account: Fh6ResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str] | None:
        external_id = get_external_id(
            ctx.variant_context if ctx else None, "platform", account.platform,
        )
        fallback = {"PS5": "15129", "Xbox": "15130"}.get(
            account.platform, _FALLBACK_SERVER_ID,
        )
        return [external_id or fallback]

    def build_payload(
        self,
        account: Fh6ResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        return super().build_payload(account, listing, ctx)
