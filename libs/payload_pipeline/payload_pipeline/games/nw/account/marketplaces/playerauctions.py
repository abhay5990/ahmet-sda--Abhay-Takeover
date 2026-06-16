"""PlayerAuctions builder for resolved New World accounts.

Template reference: ``assets/playerauctions_templates/accounts/new-world.json``
  - game_id: 9045
  - servers (region-level): US East (9920), US West (9916),
    AP Southeast (9917), EU Central (9919), SA East (9918)
  - requiredFields: securityQA=false, parentalPassword=false
"""

from __future__ import annotations

from typing import Any

from ..models import NwResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.variant_mapping import get_external_id, get_external_name
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder

_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/NewWorld/new-world_cover.png"
)

_FALLBACK_SERVER = "US East"
_FALLBACK_SERVER_ID = "9920"


class NwPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the New World account slice."""

    @property
    def game_name(self) -> str:
        return "new-world"

    @property
    def _pa_game_display_name(self) -> str:
        return "New World"

    @property
    def game_id(self) -> int:
        return 9045

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "New World Account"

    def _get_server(
        self, account: NwResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str]:
        name = get_external_name(
            ctx.variant_context if ctx else None, "region", account.region,
        )
        return [name or _FALLBACK_SERVER]

    def _get_server_id(
        self, account: NwResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str] | None:
        eid = get_external_id(
            ctx.variant_context if ctx else None, "region", account.region,
        )
        return [eid or _FALLBACK_SERVER_ID]

    def build_payload(
        self,
        account: NwResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        return super().build_payload(account, listing, ctx)
