"""PlayerAuctions builder for resolved League of Legends accounts.

Template reference: ``assets/playerauctions_templates/accounts/league_of_legends.json``
  - game_id: 3637
  - requiredFields: securityQA=true, parentalPassword=false
  - servers: North America(3638), EU West(4143), EU Nordic and East(4144),
    Oceania(5769), Turkey(5770), Russia(5771), Latin America North(5772),
    Latin America South(5773), Brazil(6001), PBE(8605), Japan(8928),
    Southeast Asia(9496), Middle East(13870)
"""

from __future__ import annotations

from ..models import LolResolvedAccount
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Lol/league-of-legends_cover.png"
)

# region_phrase -> PlayerAuctions region name
_REGION_MAP: dict[str, str] = {
    "Latin America North": "Latin America North",
    "Europe Nordic & East": "EU Nordic and East",
    "Europe West": "EU West",
    "Turkey": "Turkey",
    "North America": "North America",
    "Russia": "Russia",
    "Vietnam": "Southeast Asia",
    "Japan": "Japan",
    "Brazil": "Brazil",
    "Latin America South": "Latin America South",
    "Singapore, Malaysia & Indonesia": "Southeast Asia",
    "Thailand": "Southeast Asia",
    "Oceania": "Oceania",
    "Philippines": "Southeast Asia",
    "Middle East": "Middle East",
    "PBE": "PBE",
}

# region_phrase -> PlayerAuctions server ID (from template)
_SERVER_ID_MAP: dict[str, str] = {
    "Latin America North": "5772",
    "Europe Nordic & East": "4144",
    "Europe West": "4143",
    "Turkey": "5770",
    "North America": "3638",
    "Russia": "5771",
    "Vietnam": "9496",
    "Japan": "8928",
    "Brazil": "6001",
    "Latin America South": "5773",
    "Singapore, Malaysia & Indonesia": "9496",
    "Thailand": "9496",
    "Oceania": "5769",
    "Philippines": "9496",
    "Middle East": "13870",
    "PBE": "8605",
}

_FALLBACK_REGION = "Southeast Asia"
_FALLBACK_SERVER_ID = "9496"


class LolPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the League of Legends account slice."""

    requires_security_qa = True
    requires_parental_password = False

    @property
    def game_name(self) -> str:
        return "league-of-legends"

    @property
    def game_id(self) -> int:
        return 3637

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Riot Account"

    def _get_server(self, account: LolResolvedAccount) -> list[str]:
        region_phrase = account.region_phrase or ""
        return [_REGION_MAP.get(region_phrase, _FALLBACK_REGION)]

    def _get_server_id(self, account: LolResolvedAccount) -> list[str] | None:
        region_phrase = account.region_phrase or ""
        return [_SERVER_ID_MAP.get(region_phrase, _FALLBACK_SERVER_ID)]
