"""Resolved models for the Clash Royale slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


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

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "account_level": FieldMeta("Account experience level.", 14),
        "king_level": FieldMeta("King tower level.", 14),
        "trophies": FieldMeta("Current trophy count.", 6500),
        "current_trophies": FieldMeta("Current season trophies.", 6500),
        "peak_trophies": FieldMeta("All-time best trophies.", 7200),
        "arena": FieldMeta("Current arena ID.", "arena_20"),
        "arena_name": FieldMeta("Current arena name.", "Legendary Arena"),
        "total_wins": FieldMeta("Total wins.", 8500),
        "total_losses": FieldMeta("Total losses.", 6200),
        "arena_level": FieldMeta("Arena level number.", 20),
        "has_brawl_stars": FieldMeta("Linked Brawl Stars account.", True),
        "brawl_stars_level": FieldMeta("Brawl Stars account level.", 180),
        "brawl_stars_trophies": FieldMeta("Brawl Stars trophy count.", 25000),
        "has_coc": FieldMeta("Linked Clash of Clans account.", True),
        "coc_th_level": FieldMeta("CoC Town Hall level.", 12),
        "coc_trophies": FieldMeta("CoC trophy count.", 4500),
        "creation_year": FieldMeta("Account creation year.", 2017),
        "account_creation_year": FieldMeta("Account creation year (alt).", 2017),
        "battle_pass_active": FieldMeta("Royale Pass active.", True),
        "player_tag": FieldMeta("Supercell player tag.", "#XYZ789ABC"),
        "account_tracker_link": FieldMeta("CR tracker profile URL.", "https://royaleapi.com/player/XYZ"),
        "brawl_stars_tracker_link": FieldMeta("Brawl Stars tracker URL.", "https://brawlify.com/stats/profile/XYZ"),
        "coc_tracker_link": FieldMeta("CoC tracker URL.", "https://clashofstats.com/players/XYZ"),
        "total_cards": FieldMeta("Total card count.", 110),
        "cards_found": FieldMeta("Cards discovered.", 108),
        "evolution_count": FieldMeta("Evolution card count.", 12),
        "elite_cards": FieldMeta("Elite / champion card names.", ["Archer Queen", "Golden Knight"]),
        "max_cards_count": FieldMeta("Max-level card count.", 45),
        "level_15_cards_count": FieldMeta("Level 15 card count.", 30),
        "level_14_cards_count": FieldMeta("Level 14 card count.", 50),
        "has_email_access": FieldMeta("Email access status.", True),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
        "win_rate": FieldMeta("Win rate percentage.", 57.8, "computed"),
    }
