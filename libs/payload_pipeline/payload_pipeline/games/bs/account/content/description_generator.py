"""Resolved-model description generation for Brawl Stars listings."""

from __future__ import annotations

from .....core.contracts import MediaBundle
from ..models import BSResolvedAccount


class BrawlStarsDescriptionGenerator:
    """Generate marketplace descriptions directly from the resolved Brawl Stars account."""

    def generate(
        self,
        account: BSResolvedAccount,
        *,
        media: MediaBundle,
        site: str = "default",
    ) -> str:
        lines: list[str] = []

        image_line = self._format_image_line(media.album_url, site)
        if image_line:
            lines.append(image_line)

        lines.extend([
            "\U0001f3c5 **Brawl Stars Account Details:**",
            "---------------------------",
            f"\U0001f3ae **Account Level:** {account.level}",
            f"\U0001f916 **Brawler Count:** {account.brawler_count}",
            f"\U0001f3c6 **Legendary Brawlers Count:** {account.legendary_brawler_count}",
            f"\U0001f3c5 **Trophy Count:** {account.trophies}",
            "",
            "Whether you're aiming to climb the ranks",
            "or enjoy the game with more customization options,",
            "this account has everything you need.",
            "",
            "\U0001f512 **Full Access**",
            "",
            "\U0001f527 **Has Warranty**",
        ])

        if account.kind != "dropshipping":
            lines.extend(["", "\u26a1\ufe0f **Instant Delivery**"])

        lines.extend([
            "",
            "\u2757 **Please don't send any questions to Supercell to avoid problem "
            "(get locked or banned) on your account.**",
        ])

        return "\n".join(lines)

    def _format_image_line(self, album_url: str | None, site: str) -> str:
        if not album_url:
            return ""
        if site.lower() == "g2g":
            return ""
        url = album_url.removeprefix("https://").removeprefix("http://")
        if site.lower() == "eldorado":
            return f"Images Link: {url}\n"
        return f"{url}\n"
