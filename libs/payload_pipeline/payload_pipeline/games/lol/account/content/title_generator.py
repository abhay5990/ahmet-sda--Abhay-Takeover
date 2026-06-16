"""Resolved-model title generation for League of Legends listings."""

from __future__ import annotations

import re

from ..models import LolResolvedAccount

# Priority order — rarest/most desirable skins first.
# Title fills left-to-right until max_length is reached.
PRIORITY_SKINS: list[str] = [
    # Tier 1 — Ultra Rare / Limited
    "PAX Twisted Fate",
    "Black Alistar",
    "King Rammus",
    "Silver Kayle",
    "Young Ryze",
    "Human Ryze",
    "PAX Jax",
    "PAX Sivir",
    "UFO Corki",
    "Rusty Blitzcrank",
    "Championship Riven 2012",
    "Victorious Jarvan IV",
    "Judgment Kayle",
    "Triumphant Ryze",
    "Grey Warwick",
    "Medieval Twitch",
    "Riot Squad Singed",
    "Riot K-9 Nasus",
    "Riot Kayle",
    "Riot Graves",
    "Urfwick",
    "Urf the Manatee Warwick",
    # Tier 2 — Popular / High Demand
    "Galaxy Slayer Zed",
    "Nightbringer Yasuo",
    "Dark Cosmic Jhin",
    "Elementalist Lux",
    "PROJECT: Vayne",
    "Star Guardian Jinx",
    "High Noon Lucian",
    "God Fist Lee Sin",
    "Storm Dragon Lee Sin",
    "Spirit Blossom Ahri",
    "K/DA Akali",
    "Spirit Blossom Yasuo",
    "High Noon Yone",
    "Spirit Blossom Yone",
    "Battle Academia Ezreal",
    "K/DA ALL OUT Kai'Sa",
    "Soul Fighter Samira",
    "DJ Sona",
    "Pulsefire Ezreal",
    "K/DA ALL OUT Seraphine",
    # Tier 3 — Notable
    "Dawnbringer Riven",
    "Battle Queen Katarina",
    "Ashen Knight Pyke",
    "PROJECT: Zed",
    "Shockblade Zed",
    "Empyrean Zed",
    "Debonair Zed",
    "Prestige PROJECT: Zed",
    "Prestige Spirit Blossom Zed",
    "Prestige Inkshadow Yasuo",
    "Truth Dragon Yasuo",
    "Dream Dragon Yasuo",
    "Inkshadow Yasuo",
    "True Damage Yasuo",
    "Prestige True Damage Yasuo",
    "Dawnbringer Yone",
    "Ocean Song Yone",
    "Inkshadow Yone",
    "HEARTSTEEL Yone",
    "Prestige HEARTSTEEL Yone",
    "Peacemaker High Noon Yone",
    "Spirit Guard Udyr",
    "Gun Goddess Miss Fortune",
    "Cosmic Jhin",
    "High Noon Jhin",
    "PROJECT: Jhin",
    "Mythmaker Jhin",
    "Blood Moon Jhin",
    "Shan Hai Scrolls Jhin",
    "Prestige Dark Cosmic Erasure Jhin",
    "Star Guardian Ahri",
    "K/DA Ahri",
    "K/DA ALL OUT Ahri",
    "Prestige K/DA Ahri",
    "Coven Ahri",
    "Elderwood Ahri",
    "Arcade Ahri",
    "Spirit Blossom Evelynn",
    "K/DA Evelynn",
    "K/DA ALL OUT Evelynn",
    "Prestige K/DA Evelynn",
    "Blood Moon Evelynn",
    "Coven Evelynn",
    "K/DA Kai'Sa",
    "Prestige K/DA Kai'Sa",
    "Star Guardian Kai'Sa",
    "Bullet Angel Kai'Sa",
    "IG Kai'Sa",
    "Lagoon Dragon Kai'Sa",
    "Inkshadow Kai'Sa",
    "K/DA ALL OUT Akali",
    "True Damage Akali",
    "Star Guardian Akali",
    "Coven Akali",
    "Prestige K/DA Akali",
    "Prestige Coven Akali",
    "PROJECT: Akali",
    "Infernal Akali",
    "Crime City Nightmare Akali",
    "Stinger Akali",
    "Star Guardian Lux",
    "Cosmic Lux",
    "Dark Cosmic Lux",
    "Battle Academia Lux",
    "Prestige Battle Academia Lux",
    "Porcelain Lux",
    "Prestige Porcelain Lux",
    "Spirit Blossom Lux",
    "Prestige Spirit Blossom Lux",
    "Empyrean Lux",
    "Battle Cat Jinx",
    "Prestige Battle Cat Jinx",
    "Firecracker Jinx",
    "Odyssey Jinx",
    "Zombie Slayer Jinx",
    "Ambitious Elf Jinx",
    "Arcane Jinx",
    "Star Guardian Xayah",
    "Brave Phoenix Xayah",
    "Prestige Brave Phoenix Xayah",
    "Star Guardian Rakan",
    "Dragonmancer Rakan",
    "Prestige Dragonmancer Rakan",
    "Sentinel Vayne",
    "Spirit Blossom Vayne",
    "Firecracker Vayne",
    "Prestige Firecracker Vayne",
    "Soulstealer Vayne",
    "Arclight Vayne",
    "Nightbringer Vayne",
    "God-King Garen",
    "God-King Darius",
    "Dunkmaster Darius",
    "High Noon Darius",
    "High Noon Senna",
    "True Damage Senna",
    "Prestige True Damage Senna",
    "Lunar Eclipse Senna",
    "Prestige Lunar Eclipse Senna",
    "PROJECT: Senna",
    "Muay Thai Lee Sin",
    "Divine Heavenscale Lee Sin",
    "Dragon Fist Lee Sin",
    "Nightbringer Lee Sin",
    "Prestige Nightbringer Lee Sin",
    "Soul Fighter Pyke",
    "Prestige Soul Fighter Pyke",
    "PROJECT: Pyke",
    "Blood Moon Pyke",
    "Dark Star Pyke",
]

_PRIORITY_LOOKUP: dict[str, int] = {
    name.lower(): idx for idx, name in enumerate(PRIORITY_SKINS)
}


def match_notable_skins(skin_names: list[str]) -> list[str]:
    """Return skin names that appear in the priority list, sorted by priority."""
    matched: list[tuple[int, str]] = []
    for name in skin_names:
        idx = _PRIORITY_LOOKUP.get(name.lower())
        if idx is not None:
            matched.append((idx, name))
    matched.sort(key=lambda t: t[0])
    return [name for _, name in matched]


class LolTitleGenerator:
    """Generate marketplace titles from the resolved LOL account."""

    def generate(
        self,
        account: LolResolvedAccount,
        *,
        marketplace: str = "default",
        is_dropshipping: bool = False,
    ) -> str:
        if marketplace.lower() == "g2g":
            return self._build(account, max_length=120)
        return self._build(account, max_length=138)

    def _build(
        self,
        account: LolResolvedAccount,
        *,
        max_length: int,
    ) -> str:
        region = _format_region(account.region)
        champion_str = _format_champion_count(account.champion_count)
        be_str = f"{account.blue_essence} BE" if account.blue_essence > 5000 else ""
        oe_str = f"{account.orange_essence} OE" if account.orange_essence > 3000 else ""
        rp_str = f"{account.riot_points} RP" if account.riot_points > 500 else ""

        # Fixed parts — always included if they fit
        fixed_parts = [
            region,
            account.rank or "UNRANKED",
            f"Level {account.level}" if account.level else "",
            f"{account.skin_count} Skins",
            champion_str,
            be_str,
            oe_str,
            rp_str,
        ]

        # Notable skins — fill remaining space by priority
        notable = match_notable_skins(account.skin_names)

        return _assemble_with_fill(fixed_parts, notable, max_length=max_length)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _format_region(region: str) -> str:
    if not region or region == "UNKNOWN":
        return "UNKNOWN"
    return re.sub(r"\d+", "", region)


def _format_champion_count(count: int) -> str:
    if count >= 160:
        return "All Champs"
    if count > 90:
        return f"Nearly All Champs ({count})"
    return f"{count} Champions"


def _assemble_with_fill(
    fixed: list[str],
    fill: list[str],
    *,
    max_length: int,
) -> str:
    """Assemble fixed parts, then fill remaining space with skin names."""
    separator = " | "
    sep_len = len(separator)

    built: list[str] = []
    current_length = 0

    # Add fixed parts
    for part in fixed:
        if not part:
            continue
        item_len = len(part) + (sep_len if built else 0)
        if current_length + item_len > max_length:
            continue  # skip this fixed part but try others
        built.append(part)
        current_length += item_len

    # Fill remaining space with notable skins
    for skin in fill:
        item_len = len(skin) + (sep_len if built else 0)
        if current_length + item_len > max_length:
            break
        built.append(skin)
        current_length += item_len

    return separator.join(built)
