"""PlayerAuctions builder for resolved Genshin Impact accounts.

Template reference: ``assets/playerauctions_templates/accounts/genshin_impact.json``
  - game_id: 9334
  - requiredFields: securityQA=false, parentalPassword=false
  - servers: America(9335), Europe(9336), Asia(9337), TW/HK/MO(10104)
"""

from __future__ import annotations

import re

from ..models import GenshinResolvedAccount
from .....core.contracts import BuildContext
from .....core.variant_mapping import get_external_id, get_external_name
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Genshin/genshin-impact_cover.png"
)

_FALLBACK_SERVER = "Europe"
_FALLBACK_SERVER_ID = "9336"


class GenshinImpactPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the Genshin Impact account slice."""

    @property
    def game_name(self) -> str:
        return "genshin-impact"

    @property
    def game_id(self) -> int:
        return 9334

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "miHoYo Account"

    def _get_server(
        self, account: GenshinResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str]:
        region = (account.region or "").lower()
        name = get_external_name(
            ctx.variant_context if ctx else None, "region", region,
        )
        return [name or _FALLBACK_SERVER]

    def _get_server_id(
        self, account: GenshinResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str] | None:
        region = (account.region or "").lower()
        eid = get_external_id(
            ctx.variant_context if ctx else None, "region", region,
        )
        return [eid or _FALLBACK_SERVER_ID]

    def _format_delivery(self, account: GenshinResolvedAccount) -> str:
        """Custom delivery: does not filter 'Not Found' values."""
        c = account.credentials
        lines = [
            f"miHoYo Account -> {c.login}",
            f"miHoYo Account Password -> {c.password}",
        ]
        if c.email_login:
            lines.append(f"E-mail -> {c.email_login}")
            if c.email_password:
                lines.append(f"E-mail Password -> {c.email_password}")
            if c.email_login_link:
                link = re.sub(r"^https?://", "", c.email_login_link)
                lines.append(f"E-mail Login Link ->\n\t{link}")
        lines.append(
            "Important: Do not make any dispute or leave negative feedback "
            "before we contact you in case of any problem. We resolve all issues for sure!"
        )
        return "\n".join(lines)
