"""PlayerAuctions builder for resolved Genshin Impact accounts.

Template reference: ``assets/playerauctions_templates/accounts/genshin_impact.json``
  - game_id: 9334
  - requiredFields: securityQA=false, parentalPassword=false
  - servers: America(9335), Europe(9336), Asia(9337), TW/HK/MO(10104)
"""

from __future__ import annotations

import re

from ..models import GenshinResolvedAccount
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Genshin/genshin-impact_cover.png"
)

# Region-based server mapping (from template).
_REGION_SERVER: dict[str, str] = {
    "na": "America",
    "eu": "Europe",
    "asia": "Asia",
    "tw": "TW/HK/MO",
}

_SERVER_ID_MAP: dict[str, str] = {
    "na": "9335",
    "eu": "9336",
    "asia": "9337",
    "tw": "10104",
}

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

    def _get_server(self, account: GenshinResolvedAccount) -> list[str]:
        region = account.region or ""
        return [_REGION_SERVER.get(region.lower(), _FALLBACK_SERVER)]

    def _get_server_id(self, account: GenshinResolvedAccount) -> list[str] | None:
        region = account.region or ""
        return [_SERVER_ID_MAP.get(region.lower(), _FALLBACK_SERVER_ID)]

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
