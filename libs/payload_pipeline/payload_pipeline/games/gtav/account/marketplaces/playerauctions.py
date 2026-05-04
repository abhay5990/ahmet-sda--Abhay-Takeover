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

import re
from typing import Any

from ..models import GtavResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.base import _DISCLAIMER
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder


_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Gta/gta-v_cover.png"
)

# main_platform -> PA server name (Steam default for PC variants)
_SERVER_NAME_MAP: dict[str, str] = {
    "PlayStation 5": "PS5",
    "Xbox Series X/S": "Xbox Series",
    "PlayStation 4": "PS4",
    "Xbox One": "XBOX ONE",
    "PC - Enhanced": "PC-Steam-Enhanced",
    "PC - Legacy": "PC-Steam-Legacy",
}

# main_platform -> PA server ID (Steam default for PC variants)
_SERVER_ID_MAP: dict[str, str] = {
    "PlayStation 5": "9874",
    "Xbox Series X/S": "9889",
    "PlayStation 4": "5921",
    "Xbox One": "5922",
    "PC - Enhanced": "14270",
    "PC - Legacy": "5920",
}

_FALLBACK_SERVER = "PC-Steam-Legacy"
_FALLBACK_SERVER_ID = "5920"


class GtavPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the GTA V account slice."""

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

    def _get_server(self, account: GtavResolvedAccount) -> list[str]:
        platform = account.main_platform or ""
        return [_SERVER_NAME_MAP.get(platform, _FALLBACK_SERVER)]

    def _get_server_id(self, account: GtavResolvedAccount) -> list[str] | None:
        platform = account.main_platform or ""
        return [_SERVER_ID_MAP.get(platform, _FALLBACK_SERVER_ID)]

    def build_payload(
        self,
        account: GtavResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        return super().build_payload(account, listing, ctx)

    def _format_delivery(self, account: GtavResolvedAccount) -> str:
        """Custom delivery with security_email and birthday fields."""
        c = account.credentials
        lines = [
            f"Rockstar Login -> {c.login}",
            f"Rockstar Password -> {c.password}",
        ]
        if c.email_login and c.email_login != "Not Found":
            lines.append(f"E-mail -> {c.email_login}")
            if c.email_password and c.email_password != "Not Found":
                lines.append(f"E-mail Password -> {c.email_password}")
            if c.email_login_link:
                link = re.sub(r"^https?://", "", c.email_login_link)
                lines.append(f"E-mail Login Link ->\n\t{link}")
        if account.security_email:
            lines.append(f"Security Email -> {account.security_email}")
            if account.security_email_password:
                lines.append(f"Security Email Password -> {account.security_email_password}")
        if account.birthday:
            lines.append(f"Birthday -> {account.birthday}")
        lines.append(_DISCLAIMER)
        return "\n".join(lines)
