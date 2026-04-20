"""Resolved-model description generation for League of Legends listings."""

from __future__ import annotations

import re

from .....core.contracts import MediaBundle
from ..models import LolResolvedAccount


class LolDescriptionGenerator:
    """Generate marketplace descriptions from the resolved LOL account."""

    def generate(
        self,
        account: LolResolvedAccount,
        *,
        media: MediaBundle,
        marketplace: str = "default",
        is_dropshipping: bool = False,
    ) -> str:
        region = _format_region(account.region)
        lines: list[str] = []

        # Album link at the top
        album_text = _format_link("Images Link", media.album_url, marketplace)
        if album_text:
            lines.append(album_text)

        # Account details header
        lines.extend([
            "League of Legends Account Details:",
            "-----------------------------------",
            "Handmade",
            f"Region: {region}",
            f"Level: {account.level}",
            f"Skin Count: {account.skin_count}",
            f"Champion Count: {account.champion_count}",
            f"Blue Essence (BE): {account.blue_essence}",
        ])

        if account.riot_points >= 300:
            lines.append(f"Riot Points (RP): {account.riot_points}")
        if account.orange_essence >= 500:
            lines.append(f"Orange Essence (OE): {account.orange_essence}")

        # Motivational footer + access info
        lines.extend([
            "",
            "Whether you're aiming to climb the ranks",
            "or enjoy the game with more customization options,",
            "this account has everything you need.",
            "Full Access",
            "",
            "Has Warranty",
            "",
        ])
        if not is_dropshipping:
            lines.extend(["Instant Delivery", ""])

        lines.extend([
            "",
            " Only playable on the specified region - "
            "Contacting Riot Games for region change will cause ban.",
            "",
            "Note: DO NOT CONTACT RIOT GAMES FOR ANY REASON!",
        ])

        description = "\n".join(lines)

        if marketplace in ("player", "playerauctions"):
            description = description.replace("\n", "<br>")

        if len(description) > 2000:
            description = description[:1997] + "..."

        return description


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _format_region(region: str) -> str:
    if not region or region == "UNKNOWN":
        return "UNKNOWN"
    return re.sub(r"\d+", "", region)


def _format_link(label: str, url: str | None, marketplace: str) -> str:
    if not url or marketplace == "gameboost":
        return ""
    clean = url.removeprefix("https://").removeprefix("http://")
    return f"{label}: \n\t{clean}"
