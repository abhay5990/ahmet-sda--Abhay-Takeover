"""PlayerAuctions builder for resolved Xbox accounts.

Template reference: ``assets/playerauctions_templates/accounts/xbox.json``
  - game_id: 4876
  - servers: Main Server (4877)
  - requiredFields: securityQA=true, parentalPassword=true
    (both sent as empty strings — generic credential delivery)
"""

from __future__ import annotations

from typing import Any

from ..models import XboxResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder

_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Xbox/xbox_cover.png"
)


class XboxPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the Xbox account slice."""

    @property
    def game_name(self) -> str:
        return "xbox"

    @property
    def _pa_game_display_name(self) -> str:
        return "Xbox"

    @property
    def game_id(self) -> int:
        return 4876

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Xbox Account"

    def _get_server(
        self, account: XboxResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str]:
        return ["Main Server"]

    def _get_server_id(
        self, account: XboxResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str] | None:
        return ["4877"]

    def build_payload(
        self,
        account: XboxResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        return super().build_payload(account, listing, ctx)
