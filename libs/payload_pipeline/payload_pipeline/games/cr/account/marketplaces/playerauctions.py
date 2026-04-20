"""PlayerAuctions builder for resolved Clash Royale accounts."""

from __future__ import annotations

from ..models import CrResolvedAccount
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/ClashRoyale/clashroyale_cover.png"
)


class CrPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the Clash Royale account slice."""

    @property
    def game_name(self) -> str:
        return "clash-royale"

    @property
    def game_id(self) -> int:
        return 8461

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Supercell ID"

    def _get_server(self, account: CrResolvedAccount) -> list[str]:
        return ["Main Server"]

    def _get_server_id(self, account: CrResolvedAccount) -> list[str] | None:
        return ["8462"]
