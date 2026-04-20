"""Resolved-model title generation for Fortnite listings."""

from __future__ import annotations

from ..models import FortniteResolvedAccount


_SPECIAL_SKINS = [
    "Renegade Raider", "OG Ghoul Trooper", "OG Skull Trooper",
    "Aerial Assault Trooper", "Wildcat", "Wonder", "Black Knight",
    "Honor Guard", "IKONIK", "Travis Scott", "Galaxy",
    "Sparkle Specialist", "Royale Knight", "The Reaper",
    "Elite Agent", "Blue Squire", "Omega", "Lara Croft",
]

_PRIORITY_ITEMS = [
    "Leviathan Axe", "Merry Mint Axe", "Raider's Revenge",
    "Floss", "Take The L",
]

_CHEAP_ACCOUNT_ITEMS = ["Mako", "Reaper"]

_SPECIAL_SET = {s.lower() for s in _SPECIAL_SKINS}
_PRIORITY_SET = {s.lower() for s in _PRIORITY_ITEMS}
_CHEAP_SET = {s.lower() for s in _CHEAP_ACCOUNT_ITEMS}


class FortniteTitleGenerator:
    """Generate marketplace titles from the resolved Fortnite account."""

    def generate(
        self,
        account: FortniteResolvedAccount,
        *,
        marketplace: str = "default",
    ) -> str:
        if marketplace.lower() == "g2g":
            return self._build(account, max_length=120, include_suffix=False)
        return self._build(account, max_length=150, include_suffix=True)

    def _build(
        self,
        account: FortniteResolvedAccount,
        *,
        max_length: int,
        include_suffix: bool,
    ) -> str:
        parts: list[str] = []

        # Platform
        parts.append(_platform_string(account))

        # Skin count
        parts.append(f"{account.skin_count} skins")

        # V-bucks
        if account.platform == "EpicPC" and account.v_bucks >= 500:
            parts.append(f"{account.v_bucks} V-bucks")

        # Priority items (pickaxes/emotes)
        titles_lower = {t.lower() for t in account.cosmetic_titles}
        for item in _PRIORITY_ITEMS:
            if item.lower() in titles_lower:
                parts.append(item)

        # OG STW check
        if "rose team leader" in titles_lower:
            parts.append("OG STW")

        # Special skins
        used = {p.lower() for p in parts}
        for skin in _SPECIAL_SKINS:
            if skin.lower() in titles_lower and skin.lower() not in used:
                parts.append(skin)
                used.add(skin.lower())

        # Cheap account items
        if account.price < 25:
            for item in _CHEAP_ACCOUNT_ITEMS:
                if item.lower() in titles_lower and item.lower() not in used:
                    label = "Reaper Axe" if item == "Reaper" else item
                    parts.append(label)
                    used.add(item.lower())

        # Remaining cosmetics
        for title in account.cosmetic_titles:
            if title.lower() not in used:
                parts.append(title)
                used.add(title.lower())

        return _assemble(parts, max_length=max_length, include_suffix=include_suffix)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _platform_string(account: FortniteResolvedAccount) -> str:
    platforms = ["PC"]
    if account.psn_linkable:
        platforms.append("PSN")
    if account.xbox_linkable:
        platforms.append("XBOX")
    return "[" + "/".join(platforms) + "]"


def _assemble(parts: list[str], *, max_length: int, include_suffix: bool) -> str:
    separator = " | "
    suffix = "S4G" if include_suffix else ""
    reserved = (len(suffix) + len(separator)) if suffix else 0

    built: list[str] = []
    current_length = 0
    for part in parts:
        if not part:
            continue
        item_len = len(part) + (len(separator) if built else 0)
        if current_length + item_len > max_length - reserved:
            break
        built.append(part)
        current_length += item_len

    if suffix:
        built.append(suffix)
    return separator.join(built)
