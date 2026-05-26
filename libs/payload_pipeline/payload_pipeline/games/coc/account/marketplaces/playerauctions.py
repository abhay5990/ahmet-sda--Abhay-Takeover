"""PlayerAuctions builder for resolved Clash of Clans accounts.

Template reference: ``assets/playerauctions_templates/accounts/clash_of_clans.json``
  - game_id: 6156
  - requiredFields: securityQA=false, parentalPassword=false
  - servers: Main Server(6157)
"""

from __future__ import annotations

from ..models import CocResolvedAccount
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Coc/clash-of-clans_cover.png"
)


class CocPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the Clash of Clans account slice."""

    @property
    def _pa_game_display_name(self) -> str:
        return "Clash of Clans"

    @property
    def game_name(self) -> str:
        return "clash-of-clans"

    @property
    def game_id(self) -> int:
        return 6156

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Supercell ID"

    def _get_server(self, account: CocResolvedAccount, ctx=None) -> list[str]:
        return ["Main Server"]

    def _get_server_id(self, account: CocResolvedAccount, ctx=None) -> list[str] | None:
        return ["6157"]
