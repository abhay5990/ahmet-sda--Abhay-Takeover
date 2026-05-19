"""PlayerAuctions builder for resolved Rainbow Six Siege accounts.

Template reference: ``assets/playerauctions_templates/accounts/rainbow-six-siege.json``
  - game_id: 7773
  - requiredFields: securityQA=true, parentalPassword=true
  - servers: PC(7774), PlayStation(7775), Xbox(7776)
"""

from __future__ import annotations

from ..models import R6ResolvedAccount
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/R6/rainbow-six-siege_cover.png"
)

# PA server name -> server ID
_SERVER_ID_MAP: dict[str, str] = {
    "PC": "7774",
    "PlayStation": "7775",
    "Xbox": "7776",
}

_FALLBACK_SERVER = "PC"
_FALLBACK_SERVER_ID = "7774"


class R6PlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the Rainbow Six Siege account slice."""

    requires_security_qa = True
    requires_parental_password = True

    @property
    def game_name(self) -> str:
        return "rainbow-six-siege"

    @property
    def game_id(self) -> int:
        return 7773

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Ubisoft Account"

    def _get_server(self, account: R6ResolvedAccount) -> list[str]:
        return [account.linkable_platforms[0] if account.linkable_platforms else _FALLBACK_SERVER]

    def _get_server_id(self, account: R6ResolvedAccount) -> list[str] | None:
        server = account.linkable_platforms[0] if account.linkable_platforms else _FALLBACK_SERVER
        return [_SERVER_ID_MAP.get(server, _FALLBACK_SERVER_ID)]
