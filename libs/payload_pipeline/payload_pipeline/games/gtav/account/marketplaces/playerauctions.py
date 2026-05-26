"""PlayerAuctions builder for resolved GTA V accounts.

Template reference: ``assets/playerauctions_templates/accounts/gta_v.json``
  - game_id: 5917
  - requiredFields: securityQA=false, parentalPassword=false
  - servers: PS5(9874), Xbox Series(9889), PS4(5921), XBOX ONE(5922),
    PC-Epic-Enhanced(14271), PC-Steam-Enhanced(14270),
    PC-Rockstar-Enhanced(14272), PC-Epic-Legacy(5919),
    PC-Rockstar-Legacy(7706), PC-Steam-Legacy(5920)

Note: ``main_platform`` does not distinguish launcher (Epic/Steam/Rockstar)
for PC variants; Steam is used as the default mapping.
"""

from __future__ import annotations

from typing import Any

from ..credentials import format_platform_credentials
from ..models import GtavResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....core.variant_mapping import get_external_id, get_external_name
from .....marketplaces.base import _DISCLAIMER
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Gta/gta-v_cover.png"
)

_FALLBACK_SERVER = "PC-Steam-Legacy"
_FALLBACK_SERVER_ID = "5920"


class GtavPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the GTA V account slice."""

    @property
    def _pa_game_display_name(self) -> str:
        return "GTA 5 Online"

    @property
    def game_name(self) -> str:
        return "grand-theft-auto-5"

    @property
    def game_id(self) -> int:
        return 5917

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Rockstar Login"

    def _get_server(
        self, account: GtavResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str]:
        platform = account.main_platform or ""
        name = get_external_name(
            ctx.variant_context if ctx else None, "platform", platform,
        )
        return [name or _FALLBACK_SERVER]

    def _get_server_id(
        self, account: GtavResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str] | None:
        platform = account.main_platform or ""
        eid = get_external_id(
            ctx.variant_context if ctx else None, "platform", platform,
        )
        return [eid or _FALLBACK_SERVER_ID]

    def build_payload(
        self,
        account: GtavResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        return super().build_payload(account, listing, ctx)

    def _format_delivery(self, account: GtavResolvedAccount) -> str:
        """Platform-aware delivery with disclaimer appended."""
        return format_platform_credentials(
            account.main_platform,
            account.credentials,
            account.credential_extras,
            strip_url_scheme=True,
            disclaimer=_DISCLAIMER,
        )
