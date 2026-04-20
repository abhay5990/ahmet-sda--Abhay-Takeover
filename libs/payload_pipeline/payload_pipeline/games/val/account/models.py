"""Resolved models for the Valorant account slice."""

from __future__ import annotations

from dataclasses import dataclass, field

from ....core.contracts import ResolvedAccountBase


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
