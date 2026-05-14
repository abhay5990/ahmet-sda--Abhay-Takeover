"""Resolved models for the League of Legends slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


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

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "region": FieldMeta("Account region.", "EUW"),
        "region_phrase": FieldMeta("Region display phrase.", "Europe West"),
        "level": FieldMeta("Summoner level.", 185),
        "rank": FieldMeta("Ranked tier.", "Gold II"),
        "rank_win_rate": FieldMeta("Ranked win rate percentage.", 54.5),
        "champion_count": FieldMeta("Owned champion count.", 120),
        "skin_count": FieldMeta("Owned skin count.", 85),
        "blue_essence": FieldMeta("Blue Essence balance.", 15000),
        "orange_essence": FieldMeta("Orange Essence balance.", 3200),
        "mythic_essence": FieldMeta("Mythic Essence balance.", 50),
        "riot_points": FieldMeta("Riot Points balance.", 1200),
        "has_email_access": FieldMeta("Email access status.", True),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
    }
