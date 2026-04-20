"""Resolved models for the Clash of Clans slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ....core.contracts import ResolvedAccountBase


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
