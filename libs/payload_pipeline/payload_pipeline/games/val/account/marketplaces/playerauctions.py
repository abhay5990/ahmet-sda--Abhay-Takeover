"""PlayerAuctions builder for resolved Valorant accounts.

Template reference: ``assets/playerauctions_templates/accounts/valorant.json``
  - game_id: 9078
  - requiredFields: securityQA=true, parentalPassword=true
  - servers: NA(9089), EU(9128), LATAM(9207), APAC(9309), BR(9208), KR(9206), TR(14995)
"""

from __future__ import annotations

from ..models import ValorantResolvedAccount
from .....core.contracts import BuildContext
from .....core.variant_mapping import get_external_id, get_external_name
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Valorant/valorant_cover.png"
)

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

    def _get_server(
        self, account: ValorantResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str]:
        region = account.region or ""
        name = get_external_name(
            ctx.variant_context if ctx else None, "region", region,
        )
        return [name or _FALLBACK_REGION]

    def _get_server_id(
        self, account: ValorantResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str] | None:
        region = account.region or ""
        eid = get_external_id(
            ctx.variant_context if ctx else None, "region", region,
        )
        return [eid or _FALLBACK_SERVER_ID]
