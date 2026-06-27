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
    skin_names: list[str] = field(default_factory=list)
    has_email_access: bool = False

    # Attribute slug overrides (from manual entry — Eldorado select IDs)
    current_rank_attr: str = ""
    previous_rank_attr: str = ""
    ranked_ready_attr: str = ""
    champion_count_attr: str = ""
    skins_attr: str = ""
    blue_essence_attr: str = ""
    riot_points_attr: str = ""

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
        "skin_names": FieldMeta("Resolved skin names from inventory.", ["Dark Cosmic Jhin", "Elementalist Lux"]),
        "has_email_access": FieldMeta("Email access status.", True),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
        "region_label": FieldMeta("Cleaned region display name.", "EUW"),
        "rank_label": FieldMeta("Rank or 'Unranked' fallback.", "Gold II"),
        "champion_label": FieldMeta("Champion count display text.", "All Champs"),
        "email_access_label": FieldMeta("Email access as Yes/No.", "Yes"),
        "be_display": FieldMeta("Blue Essence (0 if below threshold).", 15000),
        "oe_display": FieldMeta("Orange Essence (0 if below threshold).", 3200),
        "rp_display": FieldMeta("Riot Points (0 if below threshold).", 1200),
        "me_display": FieldMeta("Mythic Essence (0 if below threshold).", 50),
        "total_essence": FieldMeta("Blue + Orange Essence combined.", 18200),
        "notable_skins": FieldMeta("Priority skins found in account.", ["Dark Cosmic Jhin", "PAX Twisted Fate"]),
        "other_skins": FieldMeta("Non-priority skins.", ["Annie-Versary", "Forecast Janna"]),
        "album_url": FieldMeta("Image album URL.", "imgur.com/a/xxxxx"),
        "is_stock": FieldMeta("Whether listing is stock (not dropship).", True),
    }
