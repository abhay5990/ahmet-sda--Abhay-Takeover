"""Resolved models for the Brawl Stars slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ....core.contracts import ResolvedAccountBase


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
    brawler_names: list[str] = field(default_factory=list)
    brawlers: dict[str, Any] = field(default_factory=dict)
    has_email_access: bool = False
