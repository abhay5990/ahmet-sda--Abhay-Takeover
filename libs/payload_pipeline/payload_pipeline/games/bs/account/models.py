"""Resolved models for the Brawl Stars slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


@dataclass(slots=True)
class BSResolvedAccount(ResolvedAccountBase):
    """Single resolved Brawl Stars account after source normalization."""

    level: int = 0
    trophies: int = 0
    brawler_count: int = 0
    legendary_brawler_count: int = 0
    max_level_brawlers_count: int = 0
    rank_30_plus_count: int = 0
    mythic_count: int = 0
    battle_pass_active: bool = False
    hypercharge_count: int = 0
    skin_count: int = 0
    prestige_count: int = 0
    buffies_count: int = 0
    gems_count: int = 0
    highest_trophies: int = 0
    victories: int = 0
    creation_year: int = 0
    brawler_names: list[str] = field(default_factory=list)
    brawlers: dict[str, Any] = field(default_factory=dict)
    has_email_access: bool = False

    # Attribute slug overrides (from manual entry — Eldorado select IDs)
    rank_attr: str = ""
    trophies_attr: str = ""
    prestige_attr: str = ""
    brawlers_attr: str = ""
    maxed_brawlers_attr: str = ""
    skins_attr: str = ""
    hypercharge_attr: str = ""
    buffies_attr: str = ""
    gems_attr: str = ""

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "level": FieldMeta("Account level.", 180),
        "trophies": FieldMeta("Current trophy count.", 32000),
        "brawler_count": FieldMeta("Total brawler count.", 65),
        "legendary_brawler_count": FieldMeta("Legendary brawler count.", 8),
        "max_level_brawlers_count": FieldMeta("Max power-level brawler count.", 25),
        "rank_30_plus_count": FieldMeta("Rank 30+ brawler count.", 5),
        "mythic_count": FieldMeta("Mythic brawler count.", 12),
        "battle_pass_active": FieldMeta("Brawl Pass active.", True),
        "hypercharge_count": FieldMeta("Hypercharged brawler count.", 40),
        "skin_count": FieldMeta("Total skin count.", 150),
        "prestige_count": FieldMeta("Total prestige count.", 50),
        "buffies_count": FieldMeta("Total buffies count.", 30),
        "gems_count": FieldMeta("Gem balance.", 200),
        "highest_trophies": FieldMeta("All-time highest trophy count.", 35000),
        "victories": FieldMeta("Total victories.", 3370),
        "creation_year": FieldMeta("Account creation year.", 2023),
        "brawler_names": FieldMeta("Notable brawler names.", ["Spike", "Crow", "Leon"]),
        "has_email_access": FieldMeta("Email access status.", True),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
    }
