"""Resolved-model description generation for Fortnite listings."""

from __future__ import annotations

from datetime import datetime, timezone

from .....core.contracts import MediaBundle
from ..catalog import prioritize
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

        lines.append(_format_email_line(account.fortnite_next_change_email_date))

        lines.extend([
            "Only playable on platforms mentioned in the title.",
            "",
            "Note: Do not contact Epic Games for any reason.",
            "",
        ])

        header = "\n".join(lines)

        # Cosmetic sections — fill within remaining char budget
        sections = {cat: prioritize(items) for cat, items in account.cosmetics_by_category.items()}
        items_text = _build_item_sections(sections, budget=_CHAR_LIMIT - len(header))

        description = (header + items_text).rstrip()

        if marketplace == "playerauctions":
            description = description.replace("\n", "<br>")

        return description


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_email_line(timestamp: int) -> str:
    if timestamp:
        date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%B %d, %Y")
        return f"Mail can be changed on {date}."
    return "Changeable Email"


def _format_link(url: str | None) -> str:
    if not url:
        return ""
    clean = url.removeprefix("https://").removeprefix("http://")
    return f"Images:\n{clean}\n"



def _build_item_sections(
    sections: dict[str, list[str]],
    budget: int,
) -> str:
    """Build category sections that fit within the character budget.

    Each section shows "Some {Label}:" to indicate a representative
    sample, matching the legacy listing format.

    Budget is split fairly across non-empty categories so that a single
    large category (e.g. outfits) cannot starve the others.
    """
    # Determine which categories have items
    active_categories = [
        (cat, label) for cat, label in _CATEGORY_ORDER
        if sections.get(cat)
    ]
    if not active_categories:
        return ""

    # Fair per-category budget: divide equally, leftover goes to later cats
    per_cat_budget = budget // len(active_categories)

    result: list[str] = []
    remaining = budget

    for category, label in active_categories:
        all_items = sections[category]
        section_budget = min(per_cat_budget, remaining)

        # Try fitting items one by one within section budget
        fitted: list[str] = []
        for item in all_items:
            candidate = fitted + [item]
            section = _render_section(label, candidate)
            if len(section) > section_budget:
                break
            fitted.append(item)

        if not fitted:
            continue  # skip if even one item doesn't fit

        section = _render_section(label, fitted)
        result.append(section)
        remaining -= len(section)

        if remaining <= 0:
            break

    return "".join(result)


def _render_section(label: str, items: list[str]) -> str:
    """Render a single category section with label + items."""
    return f"Some {label}:\n{', '.join(items)}\n\n"
