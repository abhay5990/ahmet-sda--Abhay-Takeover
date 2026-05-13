"""Resolved models for the Steam slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


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

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "steam_id": FieldMeta("Steam64 ID.", "76561198012345678"),
        "country": FieldMeta("Account country.", "US"),
        "register_date": FieldMeta("Registration timestamp.", 1388534400),
        "steam_level": FieldMeta("Steam profile level.", 25),
        "total_games": FieldMeta("Total owned game count.", 150),
        "has_email_access": FieldMeta("Email access status.", True),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
        "game_titles": FieldMeta("Owned game title list.", ["CS2", "Dota 2", "Rust"], "computed"),
    }
