"""Resolved models for the R6 slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from ....core.contracts import FieldMeta, ResolvedAccountBase


@dataclass(slots=True)
class R6InventoryCategory:
    """A single inventory category with count and item names."""

    count: int = 0
    items: list[str] = field(default_factory=list)


@dataclass(slots=True)
class R6InventoryBreakdown:
    """Inventory breakdown from tracker, used for title/description generation."""

    glaciers: R6InventoryCategory = field(default_factory=R6InventoryCategory)
    black_ices: R6InventoryCategory = field(default_factory=R6InventoryCategory)
    dust_lines: R6InventoryCategory = field(default_factory=R6InventoryCategory)
    universals: R6InventoryCategory = field(default_factory=R6InventoryCategory)
    seasonals: R6InventoryCategory = field(default_factory=R6InventoryCategory)
    pro_leagues_old: R6InventoryCategory = field(default_factory=R6InventoryCategory)
    pro_leagues_new: R6InventoryCategory = field(default_factory=R6InventoryCategory)
    pilot_program: R6InventoryCategory = field(default_factory=R6InventoryCategory)
    elites: R6InventoryCategory = field(default_factory=R6InventoryCategory)
    legendary_skins: R6InventoryCategory = field(default_factory=R6InventoryCategory)
    ranked_charms: R6InventoryCategory = field(default_factory=R6InventoryCategory)
    other_skins: list[str] = field(default_factory=list)

    @property
    def has_data(self) -> bool:
        return any(
            cat.count > 0
            for cat in (
                self.glaciers, self.black_ices, self.dust_lines,
                self.universals, self.seasonals, self.pro_leagues_old,
                self.pro_leagues_new, self.pilot_program, self.elites,
                self.legendary_skins, self.ranked_charms,
            )
        )

    def racer_count(self) -> int:
        return sum(1 for name in self.universals.items if "racer" in name.lower())

    def racer_items(self) -> list[str]:
        return [name for name in self.universals.items if "racer" in name.lower()]

    def find_items(self, category: R6InventoryCategory, terms: list[str]) -> list[str]:
        found: list[str] = []
        for name in category.items:
            for term in terms:
                if term.lower() in name.lower() and term not in found:
                    found.append(term)
                    break
        return found

    def find_weapons(self, category: R6InventoryCategory, weapon_names: list[str]) -> list[str]:
        return [name for name in category.items if name in weapon_names][:3]


@dataclass(slots=True)
class R6ResolvedAccount(ResolvedAccountBase):
    """Single resolved account used after LZT and tracker merge.

    This model is the canonical input for R6 media, text composition,
    and marketplace payload building.
    """

    tracker_url: str = ""

    level: int = 0
    current_rank: str = "Unranked"
    current_rank_source: str = ""
    peak_rank: str = "Unranked"
    peak_rank_count: int = 0
    peak_rank_source: str = ""
    operators: list[str] = field(default_factory=list)
    operator_count: int = 0
    skin_names: list[str] = field(default_factory=list)
    skin_count: int = 0
    black_ice_count: int = 0
    marketplace_value: int = 0
    renown: int = 0
    credits: int = 0
    ownership_state: str = "unknown"
    has_game: bool | None = None
    use_fixed_price: bool = False

    inventory: R6InventoryBreakdown = field(default_factory=R6InventoryBreakdown)

    psn_connected: bool = False
    xbox_connected: bool = False

    @property
    def ranked_ready(self) -> bool:
        return self.level >= 50

    @property
    def linkable_platforms(self) -> list[str]:
        """Platforms a buyer can use — PC always, plus unlinked consoles."""
        platforms = ["PC"]
        if not self.psn_connected:
            platforms.append("PlayStation")
        if not self.xbox_connected:
            platforms.append("Xbox")
        return platforms

    @property
    def primary_linkable_platform(self) -> str:
        """Best single platform for marketplace listing — PlayStation > Xbox > PC."""
        if not self.psn_connected:
            return "PlayStation"
        if not self.xbox_connected:
            return "Xbox"
        return "PC"

    @property
    def ownership_text(self) -> str:
        if self.ownership_state == "external" or self.ownership_state == "steam":
            return (
                "Game not purchased! You need to purchase before to play.\n"
                "You can either buy the game from Ubisoft Connect to play on PC, "
                "or purchase a new Steam account with R6, link it to Ubisoft, and then play!"
            )
        if self.ownership_state == "owned":
            return "This account has the game, You don't have to buy it again."
        return ""

    @property
    def platform_type_text(self) -> str:
        if self.ownership_state == "external" or self.ownership_state == "steam":
            return "Uplay Account | Game not Purchased"
        if self.ownership_state == "owned":
            return "Uplay Account | Has The Game"
        return "Uplay Account"

    FIELD_META: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.FIELD_META,
        "tracker_url": FieldMeta("R6 tracker profile URL.", "https://r6.tracker.network/profile/id/12345"),
        "level": FieldMeta("Account level.", 120),
        "current_rank": FieldMeta("Current ranked season rank.", "Platinum"),
        "current_rank_source": FieldMeta("Source of current rank data.", "tracker"),
        "peak_rank": FieldMeta("Highest achieved rank.", "Diamond"),
        "peak_rank_count": FieldMeta("Number of seasons at peak rank.", 2),
        "peak_rank_source": FieldMeta("Source of peak rank data.", "tracker"),
        "operators": FieldMeta("Unlocked operator names.", ["Ash", "Jager", "Mira"]),
        "operator_count": FieldMeta("Unlocked operator count.", 45),
        "skin_names": FieldMeta("Owned skin names.", ["Black Ice R4-C", "Glacier MP5"]),
        "skin_count": FieldMeta("Total skin count.", 150),
        "black_ice_count": FieldMeta("Black Ice skin count.", 12),
        "marketplace_value": FieldMeta("R6 marketplace inventory value.", 25000),
        "renown": FieldMeta("Renown currency balance.", 45000),
        "credits": FieldMeta("R6 Credits balance.", 600),
        "ownership_state": FieldMeta("Game ownership state.", "owned"),
        "has_game": FieldMeta("Whether account owns the game.", True),
        "use_fixed_price": FieldMeta("Use fixed pricing.", False),
        "psn_connected": FieldMeta("PSN connection status.", False),
        "xbox_connected": FieldMeta("Xbox connection status.", False),
    }

    COMPUTED_FIELDS: ClassVar[dict[str, FieldMeta]] = {
        **ResolvedAccountBase.COMPUTED_FIELDS,
        "ranked_ready": FieldMeta("Level 50+ for ranked play.", True, "computed"),
        "linkable_platforms": FieldMeta("Platforms buyer can use — PC always, plus unlinked consoles.", ["PC", "PlayStation", "Xbox"], "computed"),
        "primary_linkable_platform": FieldMeta("Best single platform for listing — PSN > Xbox > PC.", "PlayStation", "computed"),
        "ownership_text": FieldMeta("Game ownership description.", "This account has the game, You don't have to buy it again.", "computed"),
        "platform_type_text": FieldMeta("Platform type label.", "Uplay Account | Has The Game", "computed"),
        # Inventory breakdown counts and items
        "glacier_count": FieldMeta("Glacier skin count.", 2, "computed"),
        "glacier_items": FieldMeta("Glacier skin names.", ["Glacier Black Ice MP5", "Glacier SMG-11"], "computed"),
        "black_ice_count": FieldMeta("Black Ice skin count (from inventory).", 12, "computed"),
        "black_ice_items": FieldMeta("Black Ice skin names.", ["Black Ice R4-C", "Black Ice MP7"], "computed"),
        "dust_line_count": FieldMeta("Dust Line skin count.", 1, "computed"),
        "dust_line_items": FieldMeta("Dust Line skin names.", ["Dust Line 556xi"], "computed"),
        "universal_count": FieldMeta("Universal skin count.", 5, "computed"),
        "universal_items": FieldMeta("Universal skin names.", ["Racer AK12", "Racer R4-C"], "computed"),
        "seasonal_count": FieldMeta("Seasonal skin count.", 8, "computed"),
        "seasonal_items": FieldMeta("Seasonal skin names.", ["Wind Bastion MP5", "Ember Rise F2"], "computed"),
        "pro_league_old_count": FieldMeta("Old Pro League skin count.", 3, "computed"),
        "pro_league_old_items": FieldMeta("Old Pro League skin names.", ["Pro League Ash", "Pro League Jager"], "computed"),
        "pro_league_new_count": FieldMeta("New Pro League skin count.", 1, "computed"),
        "pro_league_new_items": FieldMeta("New Pro League skin names.", ["Pro League Ace"], "computed"),
        "pilot_program_count": FieldMeta("Pilot Program skin count.", 2, "computed"),
        "pilot_program_items": FieldMeta("Pilot Program skin names.", ["DarkZero Ash", "TSM Jager"], "computed"),
        "elite_count": FieldMeta("Elite skin count.", 4, "computed"),
        "elite_items": FieldMeta("Elite skin names.", ["Elite Ash", "Elite Jager", "Elite Bandit"], "computed"),
        "legendary_skin_count": FieldMeta("Legendary skin count.", 15, "computed"),
        "legendary_skin_items": FieldMeta("Legendary skin names.", ["Plasma Pink", "Fire"], "computed"),
        "ranked_charm_count": FieldMeta("Ranked charm count.", 6, "computed"),
        "ranked_charm_items": FieldMeta("Ranked charm names.", ["Diamond Y5S3", "Platinum Y6S1"], "computed"),
        "racer_count": FieldMeta("Racer universal skin count.", 2, "computed"),
        "racer_items": FieldMeta("Racer skin names.", ["Racer AK12", "Racer R4-C"], "computed"),
        "has_inventory_data": FieldMeta("Whether inventory data is available.", True, "computed"),
    }
