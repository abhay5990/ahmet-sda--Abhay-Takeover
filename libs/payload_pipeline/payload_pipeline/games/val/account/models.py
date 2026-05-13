"""Resolved models for the Valorant account slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


@dataclass(slots=True)
class ValorantResolvedAccount(ResolvedAccountBase):
    """Single resolved account used after source normalization."""

    tracker_url: str = ""
    region: str = ""
    level: int = 0
    valorant_points: int = 0
    radianite_points: int = 0
    rank_type: str = ""
    current_rank: str = "Unranked"
    previous_rank: str = "No Rank"
    last_rank: str = "No Rank"
    agent_names: list[str] = field(default_factory=list)
    skin_names: list[str] = field(default_factory=list)
    buddy_names: list[str] = field(default_factory=list)
    preview_urls: dict[str, str] = field(default_factory=dict)
    skin_count: int = 0
    agent_count: int = 0
    buddy_count: int = 0
    knife_count: int = 0
    inventory_value: int = 0

    @property
    def has_email_access(self) -> bool:
        return bool(self.credentials.email_login)

    @property
    def display_rank(self) -> str:
        rank_type = self.rank_type.lower().strip()
        if rank_type == "ranked" and self.current_rank:
            return self.current_rank
        if rank_type == "ranked_ready" and self.last_rank and self.last_rank != "No Rank":
            return f"Exp {self.last_rank}"
        if self.current_rank and self.current_rank != "Unranked":
            return self.current_rank
        return "Unranked"

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "tracker_url": FieldMeta("Tracker.gg profile URL.", "https://tracker.gg/valorant/profile/riot/user"),
        "region": FieldMeta("Account region.", "EU"),
        "level": FieldMeta("Account level.", 44),
        "valorant_points": FieldMeta("Valorant Points (VP) balance.", 1200),
        "radianite_points": FieldMeta("Radianite Points balance.", 80),
        "rank_type": FieldMeta("Rank classification type.", "ranked"),
        "current_rank": FieldMeta("Current competitive rank.", "Gold"),
        "previous_rank": FieldMeta("Previous act rank.", "Platinum"),
        "last_rank": FieldMeta("Last known rank.", "Gold"),
        "agent_names": FieldMeta("Unlocked agent names.", ["Jett", "Reyna", "Sage"]),
        "skin_names": FieldMeta("Owned skin names.", ["Prime Vandal", "Reaver Knife", "Ion Sheriff"]),
        "buddy_names": FieldMeta("Owned buddy names.", ["Brave Buddy", "YR1 Buddy"]),
        "skin_count": FieldMeta("Total skin count.", 81),
        "agent_count": FieldMeta("Unlocked agent count.", 22),
        "buddy_count": FieldMeta("Buddy count.", 15),
        "knife_count": FieldMeta("Knife skin count.", 8),
        "inventory_value": FieldMeta("Total inventory value in VP.", 12500),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
        "has_email_access": FieldMeta("Email access status.", True, "computed"),
        "display_rank": FieldMeta("Formatted display rank.", "Gold", "computed"),
    }
