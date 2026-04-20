"""Resolved models for the R6 slice."""

from __future__ import annotations

from dataclasses import dataclass, field

from ....core.contracts import ResolvedAccountBase


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

    platform_flags: dict[str, bool] = field(
        default_factory=lambda: {
            "pc": True,
            "psn": False,
            "xbox": False,
        }
    )

    @property
    def ranked_ready(self) -> bool:
        return self.level >= 50

    @property
    def available_platforms(self) -> list[str]:
        mapping = {
            "pc": "PC",
            "psn": "PlayStation",
            "xbox": "Xbox",
        }
        platforms = [mapping[key] for key, enabled in self.platform_flags.items() if enabled]
        return platforms or ["PC"]

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
