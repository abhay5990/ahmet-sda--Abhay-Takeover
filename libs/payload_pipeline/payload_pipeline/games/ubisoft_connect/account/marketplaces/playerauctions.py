"""PlayerAuctions builder for resolved Ubisoft Connect accounts."""

from __future__ import annotations

from ..models import UbisoftResolvedAccount
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Ubisoft/ubisoft_cover.png"
)


class UbisoftPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the Ubisoft Connect account slice."""

    @property
    def game_name(self) -> str:
        return "ubisoft-connect"

    @property
    def game_id(self) -> int:
        return 8485

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Ubisoft Account"

    def _get_server(self, account: UbisoftResolvedAccount) -> list[str]:
        return ["PC"]

    def _get_server_id(self, account: UbisoftResolvedAccount) -> list[str] | None:
        return ["8485"]
