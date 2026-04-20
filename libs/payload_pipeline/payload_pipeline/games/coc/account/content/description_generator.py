"""Resolved-model description generation for Clash of Clans listings."""

from __future__ import annotations

from .....core.contracts import MediaBundle
from ..models import CocResolvedAccount


class CocDescriptionGenerator:
    """Generate marketplace descriptions from the resolved CoC account."""

    def generate(
        self,
        account: CocResolvedAccount,
        *,
        media: MediaBundle,
        marketplace: str = "default",
    ) -> str:
        lines: list[str] = [
            "CLASH OF CLANS Account Details",
            "-" * 30,
        ]

        if media.album_url and marketplace != "g2g":
            url = media.album_url.removeprefix("https://").removeprefix("http://")
            lines.append(f"Account Tracker Link:\n\t{url}")

        lines.append("")

        # Main stats
        lines.append("MAIN STATS")
        lines.append(f"\u2022 Town Hall: Level {account.town_hall_level}")
        if account.account_level > 0:
            lines.append(f"\u2022 Experience Level: {account.account_level}")

        trophy_text = f"\u2022 Trophies: {account.trophies:,}"
        if account.best_trophies > account.trophies:
            trophy_text += f" (Best: {account.best_trophies:,})"
        lines.append(trophy_text)

        if account.war_stars > 0:
            lines.append(f"\u2022 War Stars: {account.war_stars}")
        lines.append("")

        # Heroes
        if account.total_heroes_level > 0:
            lines.append(f"HEROES (Total Level: {account.total_heroes_level})")
            if account.barbarian_king_level > 0:
                lines.append(f"\u2022 Barbarian King: Level {account.barbarian_king_level}")
            if account.archer_queen_level > 0:
                lines.append(f"\u2022 Archer Queen: Level {account.archer_queen_level}")
            if account.grand_warden_level > 0:
                lines.append(f"\u2022 Grand Warden: Level {account.grand_warden_level}")
            if account.royal_champion_level > 0:
                lines.append(f"\u2022 Royal Champion: Level {account.royal_champion_level}")
            lines.append("")

        # Troops
        if account.total_troops_level > 0:
            lines.append(f"TROOPS (Total Level: {account.total_troops_level})")
            lines.append("")

        # Spells
        if account.total_spells_level > 0:
            lines.append(f"SPELLS (Total Level: {account.total_spells_level})")
            lines.append("")

        # Builder Base
        if account.builder_hall_level > 0:
            lines.append("BUILDER BASE")
            lines.append(f"\u2022 Builder Hall: Level {account.builder_hall_level}")
            lines.append("")

        description = "\n".join(lines)

        if len(description) > 1900:
            last_nl = description[:1897].rfind("\n")
            if last_nl > 0:
                description = description[:last_nl] + "..."
            else:
                description = description[:1897] + "..."

        return description
