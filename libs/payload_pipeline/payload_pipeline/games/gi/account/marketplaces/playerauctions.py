"""PlayerAuctions builder for resolved Genshin Impact accounts."""

from __future__ import annotations

import re

from ..models import GenshinResolvedAccount
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Genshin/genshin-impact_cover.png"
)

# Region-based server mapping.  The old builder used random IOS/Android
# labels which are not meaningful for a cross-platform title.  We map the
# short region code to the region name instead.
_REGION_SERVER: dict[str, str] = {
    "na": "NA",
    "eu": "EU",
    "asia": "Asia",
    "tw": "TW/HK/MO",
}

_FALLBACK_SERVER = "EU"


class GenshinImpactPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the Genshin Impact account slice."""

    @property
    def game_name(self) -> str:
        return "genshin-impact"

    @property
    def game_id(self) -> int:
        return 8480

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "miHoYo Account"

    def _get_server(self, account: GenshinResolvedAccount) -> list[str]:
        region = account.region or ""
        return [_REGION_SERVER.get(region.lower(), _FALLBACK_SERVER)]

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
