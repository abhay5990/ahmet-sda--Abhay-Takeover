"""PlayerAuctions builder for resolved PSN accounts.

Template reference: ``assets/playerauctions_templates/accounts/psn.json``
  - game_id: 4880
  - servers: Main Server (6370)
  - requiredFields: securityQA=true, parentalPassword=true
    (both sent as empty strings — generic credential delivery)
"""

from __future__ import annotations

from typing import Any

from ..models import PsnResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder

_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Psn/psn_cover.png"
)


class PsnPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the PSN account slice."""

    @property
    def game_name(self) -> str:
        return "psn"

    @property
    def _pa_game_display_name(self) -> str:
        return "PSN"

    @property
    def game_id(self) -> int:
        return 4880

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "PSN Account"

    def _get_server(
        self, account: PsnResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str]:
        return ["Main Server"]

    def _get_server_id(
        self, account: PsnResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str] | None:
        return ["6370"]

    def build_payload(
        self,
        account: PsnResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        return super().build_payload(account, listing, ctx)
