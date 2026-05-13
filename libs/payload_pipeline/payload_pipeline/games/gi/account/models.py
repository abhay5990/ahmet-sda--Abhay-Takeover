"""Resolved models for the Genshin Impact slice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


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

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "region": FieldMeta("Account region.", "Europe"),
        # Genshin Impact
        "genshin_level": FieldMeta("Genshin Impact adventure rank.", 58),
        "genshin_character_count": FieldMeta("Genshin owned character count.", 35),
        "genshin_legendary_characters": FieldMeta("Genshin 5-star character count.", 12),
        "genshin_constellations": FieldMeta("Total constellation unlocks.", 25),
        "genshin_legendary_weapons": FieldMeta("Genshin 5-star weapon count.", 8),
        "genshin_achievement_count": FieldMeta("Genshin achievement count.", 450),
        "genshin_abyss_progress": FieldMeta("Spiral Abyss progress.", "12-3"),
        "genshin_activity_days": FieldMeta("Genshin active days.", 600),
        "genshin_currency": FieldMeta("Primogem balance.", 15000),
        # Honkai Star Rail
        "honkai_level": FieldMeta("Honkai Star Rail trailblaze level.", 65),
        "honkai_character_count": FieldMeta("Honkai owned character count.", 28),
        "honkai_legendary_characters": FieldMeta("Honkai 5-star character count.", 10),
        "honkai_eidolons": FieldMeta("Total eidolon unlocks.", 15),
        "honkai_legendary_weapons": FieldMeta("Honkai 5-star light cone count.", 6),
        "honkai_achievement_count": FieldMeta("Honkai achievement count.", 300),
        "honkai_abyss_progress": FieldMeta("Memory of Chaos progress.", "12"),
        "honkai_activity_days": FieldMeta("Honkai active days.", 400),
        "honkai_currency": FieldMeta("Stellar Jade balance.", 8000),
        # Zenless Zone Zero
        "zenless_level": FieldMeta("ZZZ inter-knot level.", 45),
        "zenless_character_count": FieldMeta("ZZZ owned agent count.", 18),
        "zenless_legendary_characters": FieldMeta("ZZZ S-rank agent count.", 6),
        "zenless_cinemas": FieldMeta("ZZZ cinema count.", 10),
        "zenless_achievement_count": FieldMeta("ZZZ achievement count.", 200),
        "zenless_abyss_progress": FieldMeta("Shiyu Defense progress.", "8"),
        "has_email_access": FieldMeta("Email access status.", True),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
    }
