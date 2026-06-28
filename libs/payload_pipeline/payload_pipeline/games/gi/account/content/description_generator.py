"""Resolved-model description generation for Genshin Impact listings."""

from __future__ import annotations

from .title_generator import REGION_MAP
from .....core.contracts import MediaBundle
from ..models import GenshinResolvedAccount

_CHAR_LIMIT = 1900
_NOTABLE_4STAR_MIN_CONS = 4


def _format_char(name: str, rank: int) -> str:
    """Format a character name with constellation/eidolon if > 0."""
    if rank > 0:
        return f"{name} C{rank}"
    return name


def _format_hsr_char(name: str, eidolon: int) -> str:
    if eidolon > 0:
        return f"{name} E{eidolon}"
    return name


class GenshinDescriptionGenerator:
    """Generate marketplace descriptions from the resolved Genshin account."""

    def generate(
        self,
        account: GenshinResolvedAccount,
        *,
        media: MediaBundle,
        marketplace: str = "default",
    ) -> str:
        region_label = REGION_MAP.get(account.region, account.region.upper() or "Unknown")
        lines: list[str] = []

        # Album link
        if media.album_url:
            clean = media.album_url.removeprefix("https://").removeprefix("http://")
            lines.extend([f"Images:\n{clean}", ""])

        # Header
        lines.append("Genshin Impact Account")
        header_parts = [f"Region: {region_label}", f"AR {account.genshin_level}"]
        if account.genshin_achievement_count > 0:
            header_parts.append(f"{account.genshin_achievement_count} Achievements")
        if account.genshin_activity_days > 0:
            header_parts.append(f"{account.genshin_activity_days} Active Days")
        lines.append(" | ".join(header_parts))
        if account.genshin_currency > 0:
            lines.append(f"Primogems: {account.genshin_currency}")
        if account.genshin_abyss_progress and account.genshin_abyss_progress != "-":
            lines.append(f"Spiral Abyss: {account.genshin_abyss_progress}")
        lines.append("")

        # 5-star characters
        five_stars = [c for c in account.genshin_characters if c.rarity == 5 and c.name != "Traveler"]
        if five_stars:
            names = [_format_char(c.name, c.constellation) for c in five_stars]
            lines.append(f"5-Star Characters ({len(five_stars)}):")
            lines.extend([", ".join(names), ""])

        # 5-star weapons
        weapons_5star: list[str] = []
        seen: set[str] = set()
        for c in account.genshin_characters:
            if c.weapon_rarity == 5 and c.weapon_name and c.weapon_name not in seen:
                weapons_5star.append(c.weapon_name)
                seen.add(c.weapon_name)
        if weapons_5star:
            lines.append(f"5-Star Weapons ({len(weapons_5star)}):")
            lines.extend([", ".join(weapons_5star), ""])

        # Notable 4-star constellations
        notable_4star = [
            c for c in account.genshin_characters
            if c.rarity == 4 and c.constellation >= _NOTABLE_4STAR_MIN_CONS
        ]
        if notable_4star:
            notable_4star.sort(key=lambda c: c.constellation, reverse=True)
            names = [_format_char(c.name, c.constellation) for c in notable_4star]
            lines.append("Notable 4-Star Constellations:")
            lines.extend([", ".join(names), ""])

        # Honkai Star Rail section
        if account.honkai_level:
            hsr_header = f"Honkai Star Rail | TL {account.honkai_level} | {account.honkai_character_count} Characters"
            lines.append(hsr_header)
            h5 = [c for c in account.honkai_characters if c.rarity == 5 and c.name != "Trailblazer"]
            if h5:
                h_names = [_format_hsr_char(c.name, c.eidolon) for c in h5]
                lines.append(f"5-Star ({len(h5)}): {', '.join(h_names)}")
            lines.append("")

        # Zenless Zone Zero section
        if account.zenless_level:
            zzz_header = f"Zenless Zone Zero | Level {account.zenless_level} | {account.zenless_character_count} Agents"
            lines.append(zzz_header)
            z_s = [c for c in account.zenless_characters if c.rarity >= 4]  # S-rank
            if z_s:
                z_names = [c.name for c in z_s if c.rarity == 5]
                if z_names:
                    lines.append(f"S-Rank: {', '.join(z_names)}")
            lines.append("")

        # Footer
        lines.append("Full Access | Has Warranty")

        description = "\n".join(lines).rstrip()

        if len(description) > _CHAR_LIMIT:
            description = description[:_CHAR_LIMIT]

        if marketplace == "playerauctions":
            description = description.replace("\n", "<br>")

        return description
