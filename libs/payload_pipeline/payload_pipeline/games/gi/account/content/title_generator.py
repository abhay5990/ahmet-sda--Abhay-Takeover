"""Resolved-model title generation for Genshin Impact listings."""

from __future__ import annotations

from ..models import GenshinResolvedAccount


REGION_MAP = {
    "North America": "NA",
    "Europe": "EU",
    "Asia": "Asia",
    "South America": "SA",
    "Southeast Asia": "SEA",
    "Japan": "JP",
    "TW, HK, MO": "TW",
    "China": "CN",
    "Global": "GL",
    # LZT sometimes returns short codes directly
    "na": "NA",
    "eu": "EU",
    "asia": "Asia",
}


def _char_label(name: str, constellation: int) -> str:
    """Format character name with constellation if > 0."""
    if constellation > 0:
        return f"{name} C{constellation}"
    return name


class GenshinTitleGenerator:
    """Generate marketplace titles from the resolved Genshin account."""

    def generate(
        self,
        account: GenshinResolvedAccount,
        *,
        marketplace: str = "default",
    ) -> str:
        if marketplace.lower() == "g2g":
            return self._build(account, max_length=120)
        return self._build(account, max_length=155)

    def _build(
        self,
        account: GenshinResolvedAccount,
        *,
        max_length: int,
    ) -> str:
        region = REGION_MAP.get(account.region, account.region.upper() or "UNK")
        parts: list[str] = [f"[{region}]"]

        if account.genshin_level > 0:
            parts.append(f"AR{account.genshin_level}")

        # 5-star count summary
        if account.genshin_legendary_characters > 0:
            parts.append(f"{account.genshin_legendary_characters}x5*")

        # 5-star character names with constellation
        for char in account.genshin_characters:
            if char.rarity == 5 and char.name != "Traveler":
                parts.append(_char_label(char.name, char.constellation))

        # 5-star weapons count
        if account.genshin_legendary_weapons > 0:
            parts.append(f"{account.genshin_legendary_weapons}x5*Wep")

        # HSR tag if has data
        if account.honkai_level > 0:
            parts.append(f"HSR TL{account.honkai_level}")

        return _assemble(parts, max_length=max_length)


def _assemble(parts: list[str], *, max_length: int) -> str:
    """Join parts with ' | ', dropping middle parts if too long."""
    separator = " | "

    built: list[str] = []
    current_length = 0
    for part in parts:
        if not part:
            continue
        item_len = len(part) + (len(separator) if built else 0)
        if current_length + item_len > max_length:
            break
        built.append(part)
        current_length += item_len

    return separator.join(built)
