"""Resolved models for the Clash Royale slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ....core.contracts import ResolvedAccountBase


@dataclass(slots=True)
class CrResolvedAccount(ResolvedAccountBase):
    """Single resolved Clash Royale account after source normalization."""

    account_level: int = 0
    king_level: int = 0
    trophies: int = 0
    current_trophies: int = 0
    peak_trophies: int = 0
    arena: str = ""
    arena_name: str = ""
    total_wins: int = 0
    total_losses: int = 0
    arena_level: int = 0
    has_brawl_stars: bool = False
    brawl_stars_level: int = 0
    brawl_stars_trophies: int = 0
    has_coc: bool = False
    coc_th_level: int = 0
    coc_trophies: int = 0
    creation_year: int = 0
    account_creation_year: int = 0
    battle_pass_active: bool = False
    player_tag: str = ""
    account_tracker_link: str = ""
    brawl_stars_tracker_link: str = ""
    coc_tracker_link: str = ""
    total_cards: int = 0
    cards_found: int = 0
    cards_data: dict[str, dict[str, Any]] = field(default_factory=dict)
    evolution_count: int = 0
    elite_cards: list[str] = field(default_factory=list)
    max_cards_count: int = 0
    level_15_cards_count: int = 0
    level_14_cards_count: int = 0
    has_email_access: bool = False

    @property
    def win_rate(self) -> float:
        total = self.total_wins + self.total_losses
        return (self.total_wins / total * 100) if total > 0 else 0.0
