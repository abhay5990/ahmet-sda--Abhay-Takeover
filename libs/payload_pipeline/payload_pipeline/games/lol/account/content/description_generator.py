"""Resolved-model description generation for League of Legends listings."""

from __future__ import annotations

import re

from .title_generator import match_notable_skins
from .....core.contracts import MediaBundle
from ..models import LolResolvedAccount

_MAX_DESCRIPTION_LENGTH = 2000


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

        # Account details
        lines.extend([
            "",
            f"League of Legends Account - {region}",
            "-----------------------------------",
            f"Region: {region}",
            f"Level: {account.level}",
        ])

        if account.rank:
            lines.append(f"Rank: {account.rank}")

        lines.extend([
            f"Skins: {account.skin_count}",
            f"Champions: {account.champion_count}",
            f"Blue Essence: {account.blue_essence:,}",
        ])

        if account.riot_points >= 300:
            lines.append(f"Riot Points: {account.riot_points:,}")
        if account.orange_essence >= 500:
            lines.append(f"Orange Essence: {account.orange_essence:,}")
        if account.mythic_essence >= 10:
            lines.append(f"Mythic Essence: {account.mythic_essence}")

        # Skins section — priority skins first, then the rest, fill remaining space
        notable = match_notable_skins(account.skin_names)
        notable_set = {s.lower() for s in notable}
        other_skins = [s for s in account.skin_names if s.lower() not in notable_set]
        all_skins = notable + other_skins
        if all_skins:
            lines.append("")
            lines.append("Some Skins:")
            # Build the fixed part first to know how much space we have
            fixed_text = "\n".join(lines)
            warning = _warning_block()
            remaining = _MAX_DESCRIPTION_LENGTH - len(fixed_text) - len(warning) - 20
            lines.extend(_format_skin_list(all_skins, max_chars=remaining))

        # Warning
        lines.extend([
            "",
            "Has Warranty",
            "",
            "Only playable on the specified region.",
            "DO NOT contact Riot Games for any reason.",
            "Contacting Riot will result in a ban.",
        ])

        description = "\n".join(lines)

        if marketplace in ("player", "playerauctions"):
            description = description.replace("\n", "<br>")

        if len(description) > _MAX_DESCRIPTION_LENGTH:
            description = description[:_MAX_DESCRIPTION_LENGTH - 3] + "..."

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


def _warning_block() -> str:
    return (
        "\n\nHas Warranty\n\n"
        "Only playable on the specified region.\n"
        "DO NOT contact Riot Games for any reason.\n"
        "Contacting Riot will result in a ban."
    )


def _format_skin_list(skins: list[str], *, max_chars: int) -> list[str]:
    """Format skins into lines of bullet-separated names that fit within max_chars."""
    separator = ", "
    lines: list[str] = []
    current_line: list[str] = []
    current_len = 0
    total_chars = 0
    line_max = 60  # soft wrap per line for readability

    for skin in skins:
        skin_len = len(skin) + (len(separator) if current_line else 0)

        # Check total budget
        if total_chars + skin_len + 1 > max_chars:
            break

        # Wrap to new line if current line is getting long
        if current_line and current_len + skin_len > line_max:
            line_text = separator.join(current_line)
            lines.append(line_text)
            total_chars += len(line_text) + 1  # +1 for newline
            current_line = []
            current_len = 0

        current_line.append(skin)
        current_len += skin_len

    if current_line:
        lines.append(separator.join(current_line))

    return lines
