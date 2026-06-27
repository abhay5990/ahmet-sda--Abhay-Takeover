"""Resolved models for the Roblox slice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


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

    # Attribute slug overrides (from manual entry — Eldorado select IDs)
    account_type_attr: str = ""
    game_attr: str = ""
    age_verified_attr: str = ""

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "roblox_id": FieldMeta("Roblox numeric user ID.", 123456789),
        "robux": FieldMeta("Current Robux balance.", 5000),
        "incoming_robux_total": FieldMeta("Total Robux spent / incoming value.", 1200),
        "inventory_price": FieldMeta("Classic inventory value.", 8500.50),
        "ugc_limited_price": FieldMeta("UGC limited inventory value.", 3200.0),
        "limited_price": FieldMeta("Limited item value.", 0.0),
        "offsale_count": FieldMeta("Offsale item count.", 42),
        "friends": FieldMeta("Friend count.", 128),
        "followers": FieldMeta("Follower count.", 2400),
        "age_verified": FieldMeta("Age verification status.", True),
        "email_verified": FieldMeta("Email verification status.", True),
        "verified": FieldMeta("General verification status.", True),
        "register_date": FieldMeta("Registration timestamp.", 946684800),
        "country": FieldMeta("Account country.", "US"),
        "has_subscription": FieldMeta("Premium subscription status.", False),
        "voice_enabled": FieldMeta("Voice chat enabled.", True),
        "xbox_connected": FieldMeta("Xbox connection status.", False),
        "psn_connected": FieldMeta("PSN connection status.", False),
        "username": FieldMeta("Account username.", "sampleuser"),
        "game_pass_total_robux": FieldMeta("Total gamepass Robux value.", 777),
        "has_email_access": FieldMeta("Email access status.", True),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
        "profile_url": FieldMeta(
            "Roblox profile URL.",
            "https://www.roblox.com/users/123456789/profile",
            "computed",
        ),
        "inventory_price_int": FieldMeta("Inventory value as integer.", 8500, "computed"),
        "ugc_limited_price_int": FieldMeta("UGC limited value as integer.", 3200, "computed"),
        "age_verified_label": FieldMeta("Yes/No label for age verification.", "Yes", "computed"),
        "register_date": FieldMeta("Registration date formatted as YYYY-MM-DD.", "2000-01-01", "computed"),
        "register_year": FieldMeta("Registration year.", "2000", "computed"),
        "letter_tag": FieldMeta("3 Letter, / 4 Letter, prefix for titles.", "4 Letter, ", "computed"),
        "letter_label": FieldMeta("3 Letter / 4 Letter label.", "4 Letter", "computed"),
    }
