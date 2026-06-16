"""PlayerAuctions builder for resolved Forza Horizon 5 accounts.

Template reference: ``assets/playerauctions_templates/accounts/forza-horizon-5.json``
  - game_id: 10635
  - servers: PC (10636), PS (14295), Xbox (10637)
  - requiredFields: securityQA=false, parentalPassword=false
"""

from __future__ import annotations

from typing import Any

from ..models import Fh5ResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.variant_mapping import get_external_id, get_external_name
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder

_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Forza/forza-horizon-5_cover.png"
)

_FALLBACK_SERVER = "PC"
_FALLBACK_SERVER_ID = "10636"


class Fh5PlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the Forza Horizon 5 account slice."""

    @property
    def game_name(self) -> str:
        return "forza-horizon-5"

    @property
    def _pa_game_display_name(self) -> str:
        return "Forza Horizon 5"

    @property
    def game_id(self) -> int:
        return 10635

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Forza Horizon 5 Account"

    def _get_server(
        self, account: Fh5ResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str]:
        name = get_external_name(
            ctx.variant_context if ctx else None, "platform", account.platform,
        )
        return [name or _FALLBACK_SERVER]

    def _get_server_id(
        self, account: Fh5ResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str] | None:
        eid = get_external_id(
            ctx.variant_context if ctx else None, "platform", account.platform,
        )
        return [eid or _FALLBACK_SERVER_ID]

    def build_payload(
        self,
        account: Fh5ResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        return super().build_payload(account, listing, ctx)
