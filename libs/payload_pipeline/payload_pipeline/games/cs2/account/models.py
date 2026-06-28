"""Resolved models for the CS2 slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase

RANK_ID_MAP: dict[int, str] = {
    1: "Silver I",
    2: "Silver II",
    3: "Silver III",
    4: "Silver IV",
    5: "Silver Elite",
    6: "Silver Elite Master",
    7: "Gold Nova I",
    8: "Gold Nova II",
    9: "Gold Nova III",
    10: "Gold Nova Master",
    11: "Master Guardian I",
    12: "Master Guardian II",
    13: "Master Guardian Elite",
    14: "Distinguished Master Guardian",
    15: "Legendary Eagle",
    16: "Legendary Eagle Master",
    17: "Supreme Master First Class",
    18: "The Global Elite",
}


@dataclass(slots=True)
class CS2ResolvedAccount(ResolvedAccountBase):
    """Single resolved account used after source normalization."""

    # Core CS2 stats
    rank_id: int = 0
    wingman_rank_id: int = 0
    premier_elo: int = 0
    is_prime: bool = False
    cs2_hours: int = 0
    profile_rank: int = 0

    # Medals
    medal_names: list[str] = field(default_factory=list)
    medal_count_raw: int = 0

    # Steam profile
    steam_level: int = 0
    country: str = ""
    has_faceit: bool = False
    has_email_access: bool = False

    # Bans
    has_vac_ban: bool = False
    market_banned: bool = False

    # Games
    game_count: int = 0
    game_titles: list[str] = field(default_factory=list)
    games: list[dict[str, Any]] = field(default_factory=list)

    # Manual attribute slug overrides (Eldorado select IDs)
    prime_attr: str = ""
    veteran_coin_attr: str = ""
    esea_attr: str = ""
    faceit_attr: str = ""

    # Legacy fields kept for manual source compatibility
    rank: str = ""
    medals: list[str] = field(default_factory=list)
    hours_played: int = 0
    medal_count_manual: int = 0

    @property
    def medal_count(self) -> int:
        if self.medal_names:
            return len(self.medal_names)
        if self.medals:
            return len(self.medals)
        return self.medal_count_raw or self.medal_count_manual

    @property
    def rank_name(self) -> str:
        if self.rank:
            return self.rank
        return RANK_ID_MAP.get(self.rank_id, "")

    @property
    def wingman_rank_name(self) -> str:
        return RANK_ID_MAP.get(self.wingman_rank_id, "")

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "rank_id": FieldMeta("Numeric competitive rank ID.", 12),
        "wingman_rank_id": FieldMeta("Numeric wingman rank ID.", 8),
        "premier_elo": FieldMeta("Premier mode ELO rating.", 14500),
        "is_prime": FieldMeta("Prime status.", True),
        "cs2_hours": FieldMeta("Total CS2 hours played.", 1568),
        "medal_names": FieldMeta("Medal names.", ["5 Year Veteran Coin", "2024 Service Medal"]),
        "steam_level": FieldMeta("Steam profile level.", 12),
        "country": FieldMeta("Steam country.", "France"),
        "has_email_access": FieldMeta("Email access status.", True),
        "game_count": FieldMeta("Total number of Steam games.", 93),
        "game_titles": FieldMeta("Game titles sorted by playtime.", ["CS2 Prime", "Rust"]),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
        "medal_count": FieldMeta("Number of service medals.", 6, "computed"),
        "rank_name": FieldMeta("Competitive rank name.", "Silver III", "computed"),
        "wingman_rank_name": FieldMeta("Wingman rank name.", "Gold Nova II", "computed"),
    }
