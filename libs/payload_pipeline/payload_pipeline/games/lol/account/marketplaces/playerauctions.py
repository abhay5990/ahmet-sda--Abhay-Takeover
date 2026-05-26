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
from .....core.contracts import BuildContext
from .....core.variant_mapping import get_external_id, get_external_name
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Lol/league-of-legends_cover.png"
)

_FALLBACK_REGION = "Southeast Asia"
_FALLBACK_SERVER_ID = "9496"


class LolPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the League of Legends account slice."""

    requires_security_qa = True
    requires_parental_password = False

    @property
    def _pa_game_display_name(self) -> str:
        return "League of Legends"

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

    def _get_server(
        self, account: LolResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str]:
        region_phrase = account.region_phrase or ""
        name = get_external_name(
            ctx.variant_context if ctx else None, "region", region_phrase,
        )
        return [name or _FALLBACK_REGION]

    def _get_server_id(
        self, account: LolResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str] | None:
        region_phrase = account.region_phrase or ""
        eid = get_external_id(
            ctx.variant_context if ctx else None, "region", region_phrase,
        )
        return [eid or _FALLBACK_SERVER_ID]
