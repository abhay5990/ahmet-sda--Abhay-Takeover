"""Resolved-model description generation for Genshin Impact listings."""

from __future__ import annotations

from .....core.contracts import MediaBundle
from ..models import GenshinResolvedAccount


class GenshinDescriptionGenerator:
    """Generate marketplace descriptions from the resolved Genshin account."""

    def generate(
        self,
        account: GenshinResolvedAccount,
        *,
        media: MediaBundle,
        marketplace: str = "default",
    ) -> str:
        lines = [
            "Genshin Impact Accounts Details:",
            "---------------------------",
            f"Region: {account.region}",
            f"Adventure Experience: {account.genshin_level}",
            f"Characters Count: {account.genshin_character_count}",
            f"Legendary Characters: {account.genshin_legendary_characters}",
            f"Legendary Weapons: {account.genshin_legendary_weapons}",
            f"Achievements: {account.genshin_achievement_count}",
        ]

        if account.genshin_currency > 0:
            lines.append(f"Primogems: {account.genshin_currency}")

        # Honkai Star Rail section
        if account.honkai_level:
            lines.extend([
                "",
                "--- Honkai Star Rail ---",
                f"Trailblaze Level: {account.honkai_level}",
                f"Characters: {account.honkai_character_count}",
                f"5-Star Characters: {account.honkai_legendary_characters}",
            ])

        # Zenless Zone Zero section
        if account.zenless_level:
            lines.extend([
                "",
                "--- Zenless Zone Zero ---",
                f"Level: {account.zenless_level}",
                f"Characters: {account.zenless_character_count}",
                f"S-Rank Characters: {account.zenless_legendary_characters}",
            ])

        description = "\n".join(lines)

        if len(description) > 1900:
            description = description[:1900]

        return description
