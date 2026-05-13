"""Resolved models for the Ubisoft Connect slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


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

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "uplay_id": FieldMeta("Ubisoft account ID.", "abc-123-def-456"),
        "country": FieldMeta("Account country.", "US"),
        "created_date": FieldMeta("Account creation timestamp.", 1451606400),
        "game_count": FieldMeta("Owned game count.", 12),
        "has_subscription": FieldMeta("Ubisoft+ subscription active.", False),
        "subscription_end_date": FieldMeta("Subscription end timestamp.", 0),
        "xbox_connected": FieldMeta("Xbox connection status.", False),
        "psn_connected": FieldMeta("PSN connection status.", False),
        "balance": FieldMeta("Ubisoft wallet balance.", "500 Units"),
        "converted_balance": FieldMeta("Wallet balance in USD.", 5.0),
        "r6_level": FieldMeta("Rainbow Six Siege level on this account.", 85),
        "r6_ban": FieldMeta("R6 ban status.", False),
        "has_email_access": FieldMeta("Email access status.", True),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
        "game_titles": FieldMeta("Owned game title list.", ["Rainbow Six Siege", "Far Cry 6", "Assassin's Creed"], "computed"),
    }
