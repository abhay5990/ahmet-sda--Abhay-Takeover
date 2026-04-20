"""Resolved models for the League of Legends slice."""

from __future__ import annotations

from dataclasses import dataclass, field

from ....core.contracts import ResolvedAccountBase


@dataclass(slots=True)
class LolResolvedAccount(ResolvedAccountBase):
    """Single resolved League of Legends account after source normalization."""

    region: str = ""
    region_phrase: str = ""
    level: int = 0
    rank: str = ""
    rank_win_rate: float = 0.0
    champion_count: int = 0
    skin_count: int = 0
    blue_essence: int = 0
    orange_essence: int = 0
    mythic_essence: int = 0
    riot_points: int = 0
    champion_ids: list[int] = field(default_factory=list)
    skin_ids: list[int] = field(default_factory=list)
    has_email_access: bool = False
