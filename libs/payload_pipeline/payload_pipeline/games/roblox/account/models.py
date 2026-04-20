"""Resolved models for the Roblox slice."""

from __future__ import annotations

from dataclasses import dataclass

from ....core.contracts import ResolvedAccountBase


@dataclass(slots=True)
class RobloxResolvedAccount(ResolvedAccountBase):
    """Single resolved Roblox account after source normalization."""

    roblox_id: int = 0
    robux: int = 0
    incoming_robux_total: int = 0
    inventory_price: float = 0.0
    ugc_limited_price: float = 0.0
    limited_price: float = 0.0
    offsale_count: int = 0
    friends: int = 0
    followers: int = 0
    age_verified: bool = False
    email_verified: bool = False
    verified: bool = False
    register_date: int = 0
    country: str = ""
    has_subscription: bool = False
    voice_enabled: bool = False
    xbox_connected: bool = False
    psn_connected: bool = False
    username: str = ""
    game_pass_total_robux: int = 0
    has_email_access: bool = False
