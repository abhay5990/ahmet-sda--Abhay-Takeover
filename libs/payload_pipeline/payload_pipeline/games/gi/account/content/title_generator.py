"""Resolved-model title generation for Genshin Impact listings."""

from __future__ import annotations

from ..models import GenshinResolvedAccount


_REGION_MAP = {
    "North America": "NA",
    "Europe": "EU",
    "Asia": "Asia",
    "South America": "SA",
    "Southeast Asia": "SEA",
    "Japan": "JP",
    "TW, HK, MO": "TW",
    "China": "CN",
    "Global": "GL",
}


class GenshinTitleGenerator:
    """Generate marketplace titles from the resolved Genshin account."""

    def generate(
        self,
        account: GenshinResolvedAccount,
        *,
        marketplace: str = "default",
    ) -> str:
        if marketplace.lower() == "g2g":
            return self._build(account, max_length=120, include_suffix=False)
        return self._build(account, max_length=155, include_suffix=True)

    def _build(
        self,
        account: GenshinResolvedAccount,
        *,
        max_length: int,
        include_suffix: bool,
    ) -> str:
        region = _REGION_MAP.get(account.region, "UNK")
        parts: list[str] = [f"[{region}]"]

        if account.genshin_level > 0:
            parts.append(f"AR{account.genshin_level}")
        if account.genshin_character_count > 0:
            parts.append(f"{account.genshin_character_count} Characters")
        if account.genshin_legendary_characters > 0:
            parts.append(f"{account.genshin_legendary_characters} Legendary")
        if account.genshin_legendary_weapons > 0:
            parts.append(f"{account.genshin_legendary_weapons} 5\u2605Weapons")
        if account.genshin_constellations > 0:
            parts.append(f"TC{account.genshin_constellations}")

        base_title = " | ".join(parts)

        suffix = " | S4G" if include_suffix else ""
        reserved = len(suffix)

        if len(base_title) + reserved > max_length:
            base_title = base_title[:max_length - reserved]

        return (base_title + suffix).strip()
