"""Resolved-model description generation for Valorant listings."""

from __future__ import annotations

import re

from .....core.contracts import MediaBundle
from ..models import ValorantResolvedAccount


_BLACKLIST_WORDS = {
    "points", "aiming", "climb", "ranks", "platforms", "mail",
    "level", "access", "full", "warranty",
}

_MAX_ITEMS_PER_CATEGORY = 25


class ValorantDescriptionGenerator:
    """Generate marketplace descriptions from the resolved Valorant account."""

    def generate(
        self,
        account: ValorantResolvedAccount,
        *,
        media: MediaBundle,
        marketplace: str = "default",
        is_dropshipping: bool = False,
    ) -> str:
        lines: list[str] = []

        # Album link at the top
        album_text = self._format_link("Images Link", media.album_url, marketplace)
        if album_text:
            lines.append(album_text)

        # Account details header
        lines.extend([
            "Valorant Account Details:",
            "---------------------------",
            f"Level: {account.level}",
            f"Skin Count: {account.skin_count}",
            f"Valorant Points (VP): {account.valorant_points}",
            f"Radianite Points (RP): {account.radianite_points}",
            "",
        ])

        # Tracker link
        tracker_text = self._format_link("Tracker Link", account.tracker_url, marketplace)
        if tracker_text:
            lines.extend([tracker_text, ""])

        # Motivational footer + access info
        lines.extend([
            "Whether you're aiming to climb the ranks",
            "or enjoy the game with more customization options,",
            "this account has everything you need.",
            "Full Access",
            "",
            "Has Warranty",
            "",
        ])
        if not is_dropshipping:
            lines.extend(["Instant Delivery", ""])

        lines.extend([
            "Only playable on the specified region - "
            "Contacting Riot Games for region change will cause ban.",
            "Note: DO NOT CONTACT RIOT GAMES FOR ANY REASON!",
        ])

        # Skins and agents
        processed = self._process_items(account.skin_names, account.agent_names)
        for category, items in processed.items():
            if items:
                lines.extend(["", f"Some {category.capitalize()}:", ", ".join(items), ""])

        description = "\n".join(lines)

        if marketplace == "player":
            description = description.replace("\n", "<br>")

        return description

    # ------------------------------------------------------------------
    # Link formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_link(label: str, url: str | None, marketplace: str) -> str:
        if not url or marketplace == "g2g":
            return ""
        clean = url.removeprefix("https://").removeprefix("http://")
        return f"{label}: \n\t{clean}"

    # ------------------------------------------------------------------
    # Item processing (blacklist + dedup)
    # ------------------------------------------------------------------

    def _process_items(
        self,
        skin_names: list[str],
        agent_names: list[str],
    ) -> dict[str, list[str]]:
        categories: dict[str, list[str]] = {
            "skins": [_to_latin(s) for s in skin_names[:_MAX_ITEMS_PER_CATEGORY]],
            "agents": [_to_latin(a) for a in agent_names[:_MAX_ITEMS_PER_CATEGORY]],
        }
        categories = _filter_blacklisted(categories)
        categories = _deduplicate_across(categories)
        return categories


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _to_latin(text: str) -> str:
    return text.translate(str.maketrans("ıİ", "ii"))


def _filter_blacklisted(categories: dict[str, list[str]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for category, items in categories.items():
        filtered: list[str] = []
        for item in items:
            words = re.split(r"\s+|[-_]", item)
            if not any(w.lower() in _BLACKLIST_WORDS for w in words):
                filtered.append(item)
        result[category] = filtered
    return result


def _deduplicate_across(categories: dict[str, list[str]]) -> dict[str, list[str]]:
    seen: set[str] = set()
    result: dict[str, list[str]] = {}
    for category, items in categories.items():
        cleaned: list[str] = []
        for item in items:
            words = re.split(r"\s+|[-_]", item)
            if not any(w.lower() in seen for w in words):
                cleaned.append(item)
                seen.update(w.lower() for w in words)
        result[category] = cleaned
    return result
