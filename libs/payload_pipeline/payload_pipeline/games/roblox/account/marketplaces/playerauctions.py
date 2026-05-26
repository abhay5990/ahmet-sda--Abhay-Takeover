"""PlayerAuctions builder for resolved Roblox accounts.

Template reference: ``assets/playerauctions_templates/accounts/roblox.json``
  - game_id: 5204
  - requiredFields: securityQA=false, parentalPassword=false
  - servers: Tax Not Covered(5205), Tax Covered(13417)

Note: Server selection (tax covered vs not) is a business-level decision,
not derived from account data.  Defaults to "Tax Not Covered".
"""

from __future__ import annotations

from ..models import RobloxResolvedAccount
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Roblox/roblox_cover.png"
)


class RobloxPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the Roblox account slice."""

    @property
    def game_name(self) -> str:
        return "roblox"

    @property
    def game_id(self) -> int:
        return 5204

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Roblox Account"

    def _get_server(self, account: RobloxResolvedAccount, ctx=None) -> list[str]:
        return ["Tax Not Covered"]

    def _get_server_id(self, account: RobloxResolvedAccount, ctx=None) -> list[str] | None:
        return ["5205"]
