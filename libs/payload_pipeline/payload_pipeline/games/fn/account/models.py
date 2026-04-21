"""Resolved models for the Fortnite slice."""

from __future__ import annotations

from dataclasses import dataclass, field

from ....core.contracts import ResolvedAccountBase


@dataclass(slots=True)
class FortniteResolvedAccount(ResolvedAccountBase):
    """Single resolved Fortnite account after source normalization."""

    level: int = 0
    platform: str = ""
    skin_count: int = 0
    pickaxe_count: int = 0
    dance_count: int = 0
    glider_count: int = 0
    v_bucks: int = 0
    lifetime_wins: int = 0
    battle_pass_level: int = 0
    season_num: int = 0
    refund_credits: int = 0
    has_real_purchases: bool = False
    psn_linkable: bool = False
    xbox_linkable: bool = False
    has_email_access: bool = False
    fortnite_next_change_email_date: int = 0
    cosmetic_titles: list[str] = field(default_factory=list)
    cosmetics_by_category: dict[str, list[str]] = field(default_factory=dict)
    preview_urls: dict[str, str] = field(default_factory=dict)
