"""PlayerAuctions builder for resolved Valorant accounts.

Template reference: ``assets/playerauctions_templates/accounts/valorant.json``
  - game_id: 9078
  - requiredFields: securityQA=true, parentalPassword=true
  - servers: NA(9089), EU(9128), LATAM(9207), APAC(9309), BR(9208), KR(9206), TR(14995)
"""

from __future__ import annotations

from ..models import ValorantResolvedAccount
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Valorant/valorant_cover.png"
)

_REGION_MAP: dict[str, str] = {
    "AP": "APAC",
    "NA": "NA",
    "EU": "EU",
    "LA": "LATAM",
    "BR": "BR",
    "KR": "KR",
    "TR": "TR",
}

_SERVER_ID_MAP: dict[str, str] = {
    "NA": "9089",
    "EU": "9128",
    "LA": "9207",
    "AP": "9309",
    "BR": "9208",
    "KR": "9206",
    "TR": "14995",
}

_FALLBACK_REGION = "KR"
_FALLBACK_SERVER_ID = "9206"


class ValorantPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the Valorant account slice."""

    requires_security_qa = True
    requires_parental_password = True

    @property
    def game_name(self) -> str:
        return "valorant"

    @property
    def game_id(self) -> int:
        return 9078

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Riot Account"

    def _get_server(self, account: ValorantResolvedAccount) -> list[str]:
        region = account.region or ""
        return [_REGION_MAP.get(region, _FALLBACK_REGION)]

    def _get_server_id(self, account: ValorantResolvedAccount) -> list[str] | None:
        region = account.region or ""
        return [_SERVER_ID_MAP.get(region, _FALLBACK_SERVER_ID)]
