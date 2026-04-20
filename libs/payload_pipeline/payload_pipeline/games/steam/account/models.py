"""Resolved models for the Steam slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ....core.contracts import ResolvedAccountBase


@dataclass(slots=True)
class SteamResolvedAccount(ResolvedAccountBase):
    """Single resolved Steam account after source normalization."""

    steam_id: str = ""
    country: str = ""
    register_date: int = 0
    steam_level: int = 0
    total_games: int = 0
    games: list[dict[str, Any]] = field(default_factory=list)
    has_email_access: bool = False

    @property
    def game_titles(self) -> list[str]:
        return [str(g.get("title", "")) for g in self.games if g.get("title")]
