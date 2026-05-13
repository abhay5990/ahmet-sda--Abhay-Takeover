"""Resolved models for the Fortnite slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


@dataclass(slots=True, frozen=True)
class CosmeticItem:
    """A single Fortnite cosmetic (skin, pickaxe, emote, or glider)."""

    id: str
    title: str
    rarity: str
    type: str
    from_shop: bool = False
    shop_price: int = 0


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
    cosmetic_items: dict[str, list[CosmeticItem]] = field(default_factory=dict)
    preview_urls: dict[str, str] = field(default_factory=dict)

    # Manual source fields (populated only from Google Sheet entries)
    manual_title: str = ""
    manual_description: str = ""
    manual_images: str = ""
    platforms: list[str] = field(default_factory=list)
    backpack_count: int = 0
    wrap_count: int = 0
    banner_count: int = 0
    spray_count: int = 0
    exclusive_count: int = 0

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "level": FieldMeta("Account level.", 250),
        "platform": FieldMeta("Primary platform.", "PC"),
        "skin_count": FieldMeta("Total skin count.", 120),
        "pickaxe_count": FieldMeta("Pickaxe count.", 45),
        "dance_count": FieldMeta("Dance / emote count.", 80),
        "glider_count": FieldMeta("Glider count.", 35),
        "v_bucks": FieldMeta("V-Bucks balance.", 2500),
        "lifetime_wins": FieldMeta("Total lifetime wins.", 350),
        "battle_pass_level": FieldMeta("Current battle pass level.", 100),
        "season_num": FieldMeta("Current season number.", 5),
        "refund_credits": FieldMeta("Available refund credits.", 3),
        "has_real_purchases": FieldMeta("Has real-money purchases.", True),
        "psn_linkable": FieldMeta("Can link to PSN.", True),
        "xbox_linkable": FieldMeta("Can link to Xbox.", True),
        "has_email_access": FieldMeta("Email access status.", True),
        "cosmetic_titles": FieldMeta("Notable cosmetic names.", ["Renegade Raider", "Black Knight", "Scenario"]),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
        "total_cosmetics": FieldMeta(
            "Total cosmetics (skins + pickaxes + dances + gliders).",
            280,
            "computed",
        ),
        "psn_linkable_label": FieldMeta("Yes/No label for PSN linkability.", "Yes", "computed"),
        "xbox_linkable_label": FieldMeta("Yes/No label for Xbox linkability.", "Yes", "computed"),
        "email_access_label": FieldMeta("Yes/No label for email access.", "Yes", "computed"),
    }
