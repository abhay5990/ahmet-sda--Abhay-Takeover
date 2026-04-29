"""PlayerAuctions builder for resolved Steam accounts.

Template reference: ``assets/playerauctions_templates/accounts/steam.json``
  - game_id: 4879
  - requiredFields: securityQA=true, parentalPassword=true
  - servers: All Server(5847)
"""

from __future__ import annotations

from ..models import SteamResolvedAccount
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Steam/steam_cover.png"
)


class SteamPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the Steam account slice."""

    requires_security_qa = True
    requires_parental_password = True

    @property
    def game_name(self) -> str:
        return "steam"

    @property
    def game_id(self) -> int:
        return 4879

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Steam Account"

    def _get_server(self, account: SteamResolvedAccount) -> list[str]:
        return ["All Server"]

    def _get_server_id(self, account: SteamResolvedAccount) -> list[str] | None:
        return ["5847"]
