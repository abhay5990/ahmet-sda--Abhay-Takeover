"""PlayerAuctions builder for resolved Clash Royale accounts.

Template reference: ``assets/playerauctions_templates/accounts/clash_royale.json``
  - game_id: 7293
  - requiredFields: securityQA=true, parentalPassword=true
  - servers: Main Server(7295)
"""

from __future__ import annotations

from ..models import CrResolvedAccount
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/ClashRoyale/clashroyale_cover.png"
)


class CrPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the Clash Royale account slice."""

    requires_security_qa = True
    requires_parental_password = True

    @property
    def game_name(self) -> str:
        return "clash-royale"

    @property
    def game_id(self) -> int:
        return 7293

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Supercell ID"

    def _get_server(self, account: CrResolvedAccount, ctx=None) -> list[str]:
        return ["Main Server"]

    def _get_server_id(self, account: CrResolvedAccount, ctx=None) -> list[str] | None:
        return ["7295"]
