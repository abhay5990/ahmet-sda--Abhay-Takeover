"""Resolved models for the Clash of Clans slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


@dataclass(slots=True)
class CocResolvedAccount(ResolvedAccountBase):
    """Single resolved Clash of Clans account after source normalization."""

    town_hall_level: int = 0
    builder_hall_level: int = 0
    account_level: int = 0
    trophies: int = 0
    best_trophies: int = 0
    war_stars: int = 0

    barbarian_king_level: int = 0
    archer_queen_level: int = 0
    grand_warden_level: int = 0
    royal_champion_level: int = 0
    total_heroes_level: int = 0
    total_troops_level: int = 0
    total_spells_level: int = 0
    total_builder_heroes_level: int = 0
    total_builder_troops_level: int = 0

    heroes: list[dict[str, Any]] = field(default_factory=list)
    troops: list[dict[str, Any]] = field(default_factory=list)
    spells: list[dict[str, Any]] = field(default_factory=list)
    hero_equipment: list[dict[str, Any]] = field(default_factory=list)
    super_troops: list[dict[str, Any]] = field(default_factory=list)

    creation_year: int = 0
    has_phone: bool = False
    battle_pass_active: bool = False
    player_tag: str = ""
    has_email_access: bool = False
    gems_count: int = 0

    # Attribute slug overrides (from manual entry — Eldorado select IDs)
    current_rank_attr: str = ""
    maxed_account_attr: str = ""
    town_hall_attr: str = ""
    gems_attr: str = ""

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "town_hall_level": FieldMeta("Town Hall level.", 15),
        "builder_hall_level": FieldMeta("Builder Hall level.", 10),
        "account_level": FieldMeta("Experience level.", 220),
        "trophies": FieldMeta("Current trophy count.", 5200),
        "best_trophies": FieldMeta("Best trophy count.", 5800),
        "war_stars": FieldMeta("War stars earned.", 1200),
        "barbarian_king_level": FieldMeta("Barbarian King level.", 80),
        "archer_queen_level": FieldMeta("Archer Queen level.", 80),
        "grand_warden_level": FieldMeta("Grand Warden level.", 60),
        "royal_champion_level": FieldMeta("Royal Champion level.", 35),
        "total_heroes_level": FieldMeta("Combined hero levels.", 255),
        "total_troops_level": FieldMeta("Combined troop levels.", 450),
        "total_spells_level": FieldMeta("Combined spell levels.", 120),
        "total_builder_heroes_level": FieldMeta("Combined builder hero levels.", 80),
        "total_builder_troops_level": FieldMeta("Combined builder troop levels.", 150),
        "creation_year": FieldMeta("Account creation year.", 2015),
        "has_phone": FieldMeta("Phone number linked.", False),
        "battle_pass_active": FieldMeta("Gold Pass active.", True),
        "player_tag": FieldMeta("Supercell player tag.", "#ABC123DEF"),
        "has_email_access": FieldMeta("Email access status.", True),
        "gems_count": FieldMeta("Gem balance.", 5000),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
    }
