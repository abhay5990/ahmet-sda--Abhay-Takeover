"""PlayerAuctions builder for resolved Fortnite accounts.

Template reference: ``assets/playerauctions_templates/accounts/fortnite.json``
  - game_id: 7876
  - requiredFields: securityQA=true, parentalPassword=true
  - servers: PC(7877), PlayStation(7878), Xbox(7879), Switch(8321),
    Android(8173), IOS(8172)
"""

from __future__ import annotations

from ..models import FortniteResolvedAccount
from .....core.contracts import BuildContext
from .....core.variant_mapping import get_external_id, get_external_name
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Fortnite/fortnite_cover.png"
)

_FALLBACK_SERVER = "PC"
_FALLBACK_SERVER_ID = "7877"


class FortnitePlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the Fortnite account slice."""

    requires_security_qa = True
    requires_parental_password = True

    @property
    def game_name(self) -> str:
        return "fortnite"

    @property
    def game_id(self) -> int:
        return 7876

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Epic Games Account"

    def _get_server(
        self, account: FortniteResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str]:
        slug = (ctx.selected_variants or {}).get("platform") if ctx else None
        if slug and ctx:
            name = get_external_name(ctx.variant_context, "platform", slug)
            if name:
                return [name]
        return [account.platform or _FALLBACK_SERVER]

    def _get_server_id(
        self, account: FortniteResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str] | None:
        slug = (ctx.selected_variants or {}).get("platform") if ctx else None
        if slug and ctx:
            eid = get_external_id(ctx.variant_context, "platform", slug)
            if eid:
                return [eid]
        return [_FALLBACK_SERVER_ID]
