"""Shared normalized source-level records for the R6 slice."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal


@dataclass(slots=True)
class R6WeaponSkin:
    """One normalized weapon-skin record extracted from a source."""

    key: str
    source: Literal["lzt", "tracker"]
    name: str = ""
    source_id: str = ""
    image_url: str = ""
    bucket: str = "unknown"
    category: str = ""


@dataclass(slots=True)
class R6RankSignal:
    """One normalized rank signal extracted from a source."""

    rank: str
    source: str
    count: int = 1
    season: str = ""
    order: int = 0
    is_current_candidate: bool = False


_PURE_WEAPON_SKIN_CATEGORIES = {
    "Black Ices",
    "Community Artist",
    "Dust Lines",
    "Epic Weapon Skins",
    "Glaciers",
    "Gold Dusts",
    "Legendary Weapon Skins",
    "Rare Weapon Skins",
    "Seasonals",
    "Uncommon Weapon Skins",
    "Universals",
}

_MIXED_WEAPON_SKIN_CATEGORIES = {
    "Apocalypse",
    "Containment",
    "Doktors Curse",
    "Freeze For All",
    "M.U.T.E Protocol",
    "Outbreak",
    "Pro Leagues",
    "Pro Leagues (New)",
    "Pro Leagues (Old)",
    "R6 Cup Rewards",
    "Rainbow Is Magic",
    "Redhammer",
    "Rengoku",
    "SI 2019 Packs",
    "Showdown",
    "Snow Brawl",
    "Special",
    "Sugar Fright",
    "Sunsplash",
    "The Grand Larceny",
    "Uplay Rewards",
    "Y4 Pilot Programs",
    "Y5 Pilot Programs",
    "Y6 Pilot Programs",
    "Y7 Pilot Programs",
    "Y8 Pilot Programs",
    "Y9 Pilot Programs",
}

_NON_WEAPON_CATEGORIES = {
    "Attachment Skins",
    "Elites",
    "Flags",
    "Influencers",
    "Ranked Charms",
    "Year Passes",
}

_NON_WEAPON_NAME_HINTS = (
    "background",
    "bundle",
    "card",
    "charm",
    "drone skin",
    "flag",
    "headgear",
    "portrait",
    "uniform",
)

_BUCKET_MAP = {
    "Black Ices": "black_ice",
    "Community Artist": "community_artist",
    "Dust Lines": "dust_line",
    "Epic Weapon Skins": "epic",
    "Glaciers": "glacier",
    "Gold Dusts": "gold_dust",
    "Legendary Weapon Skins": "legendary",
    "Pro Leagues": "pro_league",
    "Pro Leagues (New)": "pro_league",
    "Pro Leagues (Old)": "pro_league",
    "Rare Weapon Skins": "rare",
    "Seasonals": "seasonal",
    "Uncommon Weapon Skins": "uncommon",
    "Universals": "universal",
    "Y4 Pilot Programs": "pilot_program",
    "Y5 Pilot Programs": "pilot_program",
    "Y6 Pilot Programs": "pilot_program",
    "Y7 Pilot Programs": "pilot_program",
    "Y8 Pilot Programs": "pilot_program",
    "Y9 Pilot Programs": "pilot_program",
}


def build_skin_key(*, source: str, source_id: str = "", name: str = "") -> str:
    """Build a stable dedupe key for one normalized skin record."""
    token = str(source_id or "").strip()
    if token:
        return f"{source}:{token.lower()}"

    normalized_name = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower()).strip("-")
    if normalized_name:
        return f"{source}:{normalized_name}"
    return f"{source}:unknown"


def normalize_skin_bucket(category: str, *, name: str = "") -> str:
    """Map a raw category/name pair into a shared bucket vocabulary."""
    if category in _BUCKET_MAP:
        return _BUCKET_MAP[category]

    if "black ice" in str(name or "").lower():
        return "black_ice"

    if category in _MIXED_WEAPON_SKIN_CATEGORIES:
        return "event"

    return "unknown"


def is_tracker_weapon_skin_item(category: str, title: str) -> bool:
    """Return True when a tracker inventory entry looks like a weapon skin."""
    normalized_category = str(category or "").strip()
    lowered_title = str(title or "").strip().lower()
    if not normalized_category or not lowered_title:
        return False

    if normalized_category in _NON_WEAPON_CATEGORIES:
        return False

    if any(hint in lowered_title for hint in _NON_WEAPON_NAME_HINTS):
        return False

    if normalized_category in _PURE_WEAPON_SKIN_CATEGORIES:
        return True

    if normalized_category in _MIXED_WEAPON_SKIN_CATEGORIES:
        return "(" in title and ")" in title

    return False
