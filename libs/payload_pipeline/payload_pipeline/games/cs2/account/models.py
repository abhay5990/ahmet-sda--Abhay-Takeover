"""Resolved models for the CS2 slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ....core.contracts import ResolvedAccountBase


@dataclass(slots=True)
class CS2ResolvedAccount(ResolvedAccountBase):
    """Single resolved account used after source normalization."""

    rank: str = ""
    rank_id: int = 0
    premier_elo: int = 0
    medals: list[str] = field(default_factory=list)
    is_prime: bool = False
    has_email_access: bool = False
    hours_played: int = 0
    games: list[dict[str, Any]] = field(default_factory=list)

    @property
    def medal_count(self) -> int:
        return len(self.medals)
