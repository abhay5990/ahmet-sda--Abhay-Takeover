"""Resolved models for the Genshin Impact slice."""

from __future__ import annotations

from dataclasses import dataclass

from ....core.contracts import ResolvedAccountBase


@dataclass(slots=True)
class GenshinResolvedAccount(ResolvedAccountBase):
    """Single resolved miHoYo account after source normalization."""

    region: str = ""

    # Genshin Impact
    genshin_level: int = 0
    genshin_character_count: int = 0
    genshin_legendary_characters: int = 0
    genshin_constellations: int = 0
    genshin_legendary_weapons: int = 0
    genshin_achievement_count: int = 0
    genshin_abyss_progress: str = ""
    genshin_activity_days: int = 0
    genshin_currency: int = 0

    # Honkai Star Rail
    honkai_level: int = 0
    honkai_character_count: int = 0
    honkai_legendary_characters: int = 0
    honkai_eidolons: int = 0
    honkai_legendary_weapons: int = 0
    honkai_achievement_count: int = 0
    honkai_abyss_progress: str = ""
    honkai_activity_days: int = 0
    honkai_currency: int = 0

    # Zenless Zone Zero
    zenless_level: int = 0
    zenless_character_count: int = 0
    zenless_legendary_characters: int = 0
    zenless_cinemas: int = 0
    zenless_achievement_count: int = 0
    zenless_abyss_progress: str = ""

    has_email_access: bool = False
