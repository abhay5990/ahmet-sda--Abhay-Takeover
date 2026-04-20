"""Resolved models for the Ubisoft Connect slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ....core.contracts import ResolvedAccountBase


@dataclass(slots=True)
class UbisoftResolvedAccount(ResolvedAccountBase):
    """Single resolved Ubisoft Connect account after source normalization."""

    uplay_id: str = ""
    country: str = ""
    created_date: int = 0
    game_count: int = 0
    games: dict[str, Any] = field(default_factory=dict)
    has_subscription: bool = False
    subscription_end_date: int = 0
    xbox_connected: bool = False
    psn_connected: bool = False
    balance: str = ""
    converted_balance: float = 0.0
    r6_level: int = 0
    r6_ban: bool = False
    has_email_access: bool = False

    @property
    def game_titles(self) -> list[str]:
        titles = []
        if isinstance(self.games, dict):
            for game in self.games.values():
                if isinstance(game, dict) and game.get("title"):
                    titles.append(str(game["title"]))
        return titles
