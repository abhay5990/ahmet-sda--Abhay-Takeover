"""PlayerAuctions builder for resolved Brawl Stars accounts."""

from __future__ import annotations

from ..models import BSResolvedAccount
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/BrawlStars/brawlstars_cover.png"
)


class BSPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the Brawl Stars account slice."""

    @property
    def game_name(self) -> str:
        return "brawl-stars"

    @property
    def game_id(self) -> int:
        return 8463

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Supercell ID"

    def _get_server(self, account: BSResolvedAccount) -> list[str]:
        return ["Main Server"]

    def _get_server_id(self, account: BSResolvedAccount) -> list[str] | None:
        return ["8464"]
