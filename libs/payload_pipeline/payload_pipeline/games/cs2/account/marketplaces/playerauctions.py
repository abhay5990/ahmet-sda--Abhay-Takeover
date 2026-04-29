"""PlayerAuctions builder for resolved CS2 accounts.

Template reference: ``assets/playerauctions_templates/accounts/cs2.json``
  - game_id: 6903
  - requiredFields: securityQA=true, parentalPassword=false
  - servers: Steam(6905)
"""

from __future__ import annotations

from ..models import CS2ResolvedAccount
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/CS2/cs2_cover.png"
)


class CS2PlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the CS2 account slice."""

    requires_security_qa = True
    requires_parental_password = False

    @property
    def game_name(self) -> str:
        return "cs2"

    @property
    def game_id(self) -> int:
        return 6903

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Steam Account"

    def _get_server(self, account: CS2ResolvedAccount) -> list[str]:
        return ["Steam"]

    def _get_server_id(self, account: CS2ResolvedAccount) -> list[str] | None:
        return ["6905"]
