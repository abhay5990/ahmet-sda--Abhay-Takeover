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
    is_limited: bool = False
    cs2_rank_id: int = 0
    cs2_profile_rank: int = 0
    cs2_win_count: int = 0
    market_ban_end_date: int = 0
    dota2_mmr: int = 0
    dota2_win_count: int = 0
    dota2_lose_count: int = 0
    rust_kills: int = 0
    rust_deaths: int = 0

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
        "is_limited": FieldMeta("Steam limited account flag.", False),
        "cs2_rank_id": FieldMeta("CS2 competitive rank ID.", 0),
        "cs2_profile_rank": FieldMeta("CS2 profile level.", 0),
        "cs2_win_count": FieldMeta("CS2 total win count.", 0),
        "market_ban_end_date": FieldMeta("Steam market ban end timestamp.", 0),
        "dota2_mmr": FieldMeta("Dota 2 solo MMR.", 0),
        "dota2_win_count": FieldMeta("Dota 2 win count.", 0),
        "dota2_lose_count": FieldMeta("Dota 2 loss count.", 0),
        "rust_kills": FieldMeta("Rust player kill count.", 0),
        "rust_deaths": FieldMeta("Rust death count.", 0),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
        "game_titles": FieldMeta("Owned game title list.", ["CS2", "Dota 2", "Rust"], "computed"),
    }
