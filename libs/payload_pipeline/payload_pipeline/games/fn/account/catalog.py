"""Fortnite cosmetic item catalog.

List order = display priority.  First item is shown before all others
in both titles and descriptions.  Items not in this list are appended
after all catalog matches in their original source order.
"""

from __future__ import annotations

from ....shared.catalog import ValuableItem

# ---------------------------------------------------------------------------
# Valuable items — ordered by priority (index 0 = highest)
# ---------------------------------------------------------------------------

VALUABLE_ITEMS: list[ValuableItem] = [
    # Outfits — OG / extremely rare
    ValuableItem("Renegade Raider",          "outfit"),
    ValuableItem("Aerial Assault Trooper",   "outfit"),
    ValuableItem("OG Ghoul Trooper",         "outfit"),
    ValuableItem("OG Skull Trooper",         "outfit"),
    ValuableItem("Black Knight",             "outfit"),
    ValuableItem("Travis Scott",             "outfit"),
    ValuableItem("Galaxy",                   "outfit"),
    ValuableItem("IKONIK",                   "outfit"),
    ValuableItem("Honor Guard",              "outfit"),
    ValuableItem("Sparkle Specialist",       "outfit"),
    ValuableItem("Royale Knight",            "outfit"),
    ValuableItem("Blue Squire",              "outfit"),
    ValuableItem("Wildcat",                  "outfit"),
    ValuableItem("Wonder",                   "outfit"),
    ValuableItem("The Reaper",               "outfit"),
    ValuableItem("Elite Agent",              "outfit"),
    ValuableItem("Omega",                    "outfit"),
    ValuableItem("Lara Croft",               "outfit"),
    # Pickaxes
    ValuableItem("Leviathan Axe",            "pickaxe"),
    ValuableItem("Merry Mint Axe",           "pickaxe"),
    ValuableItem("Raider's Revenge",         "pickaxe"),
    ValuableItem("Mako",                     "pickaxe"),
    ValuableItem("Reaper",                   "pickaxe"),
    # Emotes
    ValuableItem("Floss",                    "emote"),
    ValuableItem("Take The L",               "emote"),
]

# Fast lookup: name → catalog index (for sorting non-catalog items after)
_VALUABLE_INDEX: dict[str, int] = {
    item.name: idx for idx, item in enumerate(VALUABLE_ITEMS)
}
_VALUABLE_NAMES: set[str] = set(_VALUABLE_INDEX)


def prioritize(cosmetics: list[str]) -> list[str]:
    """Return cosmetics sorted by catalog priority.

    Catalog items come first in list order.  Items not in the catalog
    are appended after, preserving their original relative order.
    """
    matched = [item.name for item in VALUABLE_ITEMS if item.name in set(cosmetics)]
    remaining = [c for c in cosmetics if c not in _VALUABLE_NAMES]
    return matched + remaining


def category_of(name: str) -> str | None:
    """Return the category of a catalog item, or None if not in catalog."""
    idx = _VALUABLE_INDEX.get(name)
    return VALUABLE_ITEMS[idx].category if idx is not None else None
