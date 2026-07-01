"""Resolved models for the Genshin Impact slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase
from .region import normalize_region_key


@dataclass(slots=True, frozen=True)
class GenshinCharacter:
    """A single Genshin Impact character with optional weapon info."""

    name: str
    rarity: int = 4
    element: str = ""
    level: int = 0
    constellation: int = 0
    weapon_name: str = ""
    weapon_rarity: int = 0


@dataclass(slots=True, frozen=True)
class HonkaiCharacter:
    """A single Honkai Star Rail character with optional light cone info."""

    name: str
    rarity: int = 4
    element: str = ""
    level: int = 0
    eidolon: int = 0
    weapon_name: str = ""
    weapon_rarity: int = 0


@dataclass(slots=True, frozen=True)
class ZenlessCharacter:
    """A single Zenless Zone Zero agent."""

    name: str
    rarity: int = 4
    element: str = ""
    level: int = 0
    cinema: int = 0


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

    # Character detail lists (from LZT API)
    genshin_characters: list[GenshinCharacter] = field(default_factory=list)
    honkai_characters: list[HonkaiCharacter] = field(default_factory=list)
    zenless_characters: list[ZenlessCharacter] = field(default_factory=list)

    # Derived name lists for title generation and template rendering
    genshin_5star_names: list[str] = field(default_factory=list)
    genshin_5star_weapon_names: list[str] = field(default_factory=list)
    honkai_5star_names: list[str] = field(default_factory=list)

    # Manual entry integer counts
    adventure_rank_level: int = 0
    character_count: int = 0
    legendary_weapon_count: int = 0
    primogem_count: int = 0
    events_count: int = 0

    # Attribute slug overrides (from manual entry — Eldorado select IDs)
    account_type_attr: str = ""

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
        # Character name lists
        "genshin_5star_names": FieldMeta(
            "Genshin 5-star character names.",
            ["Yoimiya", "Wanderer", "Nilou", "Shenhe"],
        ),
        "genshin_5star_weapon_names": FieldMeta(
            "Genshin 5-star weapon names.",
            ["Wolf's Gravestone", "Primordial Jade Winged-Spear"],
        ),
        "honkai_5star_names": FieldMeta(
            "Honkai 5-star character names.",
            ["Aventurine", "Dr. Ratio", "Luocha"],
        ),
        # Manual entry integer counts
        "adventure_rank_level": FieldMeta("Adventure rank from manual entry.", 55),
        "character_count": FieldMeta("5-star character count from manual entry.", 12),
        "legendary_weapon_count": FieldMeta("5-star weapon count from manual entry.", 5),
        "primogem_count": FieldMeta("Primogem count from manual entry.", 15000),
        "events_count": FieldMeta("Limited events count from manual entry.", 10),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
        "region_code": FieldMeta("Short region code (EU, NA, etc.).", "EU", "computed"),
        "genshin_5star_with_cons": FieldMeta(
            "5-star characters with constellation notation (e.g. Yoimiya C1).",
            ["Yoimiya C1", "Mona C1", "Diluc"],
            "computed",
        ),
        "notable_4star_cons": FieldMeta(
            "Notable 4-star characters with high constellations (C4+).",
            ["Bennett C5", "Xingqiu C4"],
            "computed",
        ),
        "honkai_5star_with_eidolons": FieldMeta(
            "HSR 5-star characters with eidolon notation.",
            ["Aventurine E1", "Dr. Ratio"],
            "computed",
        ),
        "hsr_summary": FieldMeta(
            "Short HSR summary for title (e.g. HSR TL54).",
            "HSR TL54",
            "computed",
        ),
    }

    @property
    def region_variant_key(self) -> str:
        """Canonical region key for variant/trade-environment lookups.

        Normalizes raw source values (LZT codes like ``eu``/``usa``/``cht``,
        or manual full names) to the ``GameVariant.source_key`` form so
        marketplace builders resolve the correct trade environment / server.
        Kept separate from :attr:`region`, which stays raw for display.
        """
        return normalize_region_key(self.region)
