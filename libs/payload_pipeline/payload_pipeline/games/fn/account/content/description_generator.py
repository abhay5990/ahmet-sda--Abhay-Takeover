"""Resolved-model description generation for Fortnite listings."""

from __future__ import annotations

from .....core.contracts import MediaBundle
from ..catalog import category_of, prioritize
from ..models import FortniteResolvedAccount

_CHAR_LIMIT = 1990

# Category display labels — order controls section order in description
_CATEGORY_ORDER: list[tuple[str, str]] = [
    ("outfit",  "Outfits"),
    ("pickaxe", "Pickaxes"),
    ("emote",   "Emotes"),
    ("glider",  "Gliders"),
    ("_other",  "Other Items"),
]


class FortniteDescriptionGenerator:
    """Generate marketplace descriptions from the resolved Fortnite account."""

    def generate(
        self,
        account: FortniteResolvedAccount,
        *,
        media: MediaBundle,
        marketplace: str = "default",
    ) -> str:
        lines: list[str] = []

        # Album link
        album_text = _format_link(media.album_url)
        if album_text:
            lines.append(album_text)

        # Core info
        lines.extend([
            "Full Access",
            "Has Warranty",
            f"Level: {account.level}",
        ])

        if account.platform == "EpicPC" and account.v_bucks >= 100:
            lines.append(f"V-Bucks: {account.v_bucks}")

        if account.battle_pass_level > 0:
            lines.append(f"Battle Pass Level: {account.battle_pass_level}")

        if account.lifetime_wins > 0:
            lines.append(f"Wins: {account.lifetime_wins}")

        if account.has_email_access:
            lines.append("Changeable Email")

        lines.extend([
            "Only playable on platforms mentioned in the title.",
            "",
            "Note: Do not contact Epic Games for any reason.",
            "",
        ])

        header = "\n".join(lines)

        # Cosmetic sections — fill within remaining char budget
        ordered = prioritize(account.cosmetic_titles)
        sections = _group_by_category(ordered)
        items_text = _build_item_sections(sections, budget=_CHAR_LIMIT - len(header))

        description = (header + items_text).rstrip()

        if marketplace == "playerauctions":
            description = description.replace("\n", "<br>")

        return description


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_link(url: str | None) -> str:
    if not url:
        return ""
    clean = url.removeprefix("https://").removeprefix("http://")
    return f"Images:\n{clean}\n"


def _group_by_category(cosmetics: list[str]) -> dict[str, list[str]]:
    """Group cosmetic names by their catalog category.

    Items not in the catalog go into "_other".
    """
    groups: dict[str, list[str]] = {}
    for name in cosmetics:
        cat = category_of(name) or "_other"
        groups.setdefault(cat, []).append(name)
    return groups


def _build_item_sections(
    sections: dict[str, list[str]],
    budget: int,
) -> str:
    """Build category sections that fit within the character budget.

    Each section shows "Some {Label}:" to indicate a representative
    sample, matching the legacy listing format.
    """
    result: list[str] = []
    remaining = budget

    for category, label in _CATEGORY_ORDER:
        all_items = sections.get(category, [])
        if not all_items:
            continue

        # Try fitting items one by one within char budget
        fitted: list[str] = []
        for item in all_items:
            candidate = fitted + [item]
            section = _render_section(label, candidate)
            if len(section) > remaining:
                break
            fitted.append(item)

        if not fitted:
            break  # no more budget for any section

        section = _render_section(label, fitted)
        result.append(section)
        remaining -= len(section)

        if remaining <= 0:
            break

    return "".join(result)


def _render_section(label: str, items: list[str]) -> str:
    """Render a single category section with label + items."""
    return f"Some {label}:\n{', '.join(items)}\n\n"
