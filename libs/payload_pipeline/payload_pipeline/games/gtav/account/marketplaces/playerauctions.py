"""PlayerAuctions builder for resolved GTA V accounts.

``server = ["IOS", "Android"]`` and ``server_id = ["8458", "8459"]`` are the
seller-wide PlayerAuctions defaults shared by nearly all games in this repo
(CoC, CS2, Rainbow, Steam, Roblox, Ubisoft, Fortnite, Genshin).  They are not
mobile-game-specific despite the names.

``game_id = 8458`` and ``game_name = "grand-theft-auto-5"`` match the legacy
builder exactly.  The old builder randomly selected one server/server_id via
probability weights; here both values are passed as a list, which is already
deterministic.
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


class GtavPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the GTA V account slice."""

    @property
    def game_name(self) -> str:
        return "grand-theft-auto-5"

    @property
    def game_id(self) -> int:
        return 8458

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Rockstar Login"

    def _get_server(self, account: GtavResolvedAccount) -> list[str]:
        return ["IOS", "Android"]

    def _get_server_id(self, account: GtavResolvedAccount) -> list[str] | None:
        return ["8458", "8459"]

    def build_payload(
        self,
        account: GtavResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        payload = super().build_payload(account, listing, ctx)
        # Custom price logic: prefer playerauctions_price over base price
        raw = account.playerauctions_price or account.price or 399
        price = self._apply_pricing(raw, ctx)
        payload["price"] = round(max(price, 0.01), 2)
        return payload

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
