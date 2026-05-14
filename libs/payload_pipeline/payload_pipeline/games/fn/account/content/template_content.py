"""Template context builder for Fortnite listing composition.

Provides build_fortnite_context() — a flat field→value dict used by
FortniteComposer when rendering {field_name} placeholder templates.
"""

from __future__ import annotations

from dataclasses import fields as dc_fields
from typing import Any

from .....core.contracts import MediaBundle, PipelineRequest
from .....core.enums import ListingKind
from ..models import FortniteResolvedAccount
from .title_generator import (
    _CHEAP_ACCOUNT_ITEMS,
    _PRIORITY_ITEMS,
    _SPECIAL_SKINS,
)


def _build_platform_label(account: FortniteResolvedAccount) -> str:
    """Build a bracketed platform tag like ``[PC/PSN/XBOX]``."""
    parts = ["PC"]
    if account.psn_linkable:
        parts.append("PSN")
    if account.xbox_linkable:
        parts.append("XBOX")
    return "[" + "/".join(parts) + "]"


def _build_title_cosmetics(
    account: FortniteResolvedAccount,
) -> tuple[list[str], bool, list[str], list[str], list[str]]:
    """Split cosmetic_titles into the same buckets as the legacy title generator.

    Returns (priority_items, has_og_stw, special_skins, cheap_items, other_cosmetics).
    All lists preserve the legacy ordering and deduplication logic.
    """
    titles_lower = {t.lower() for t in account.cosmetic_titles}
    used: set[str] = set()

    # Priority items — ordered by _PRIORITY_ITEMS definition
    priority: list[str] = []
    for item in _PRIORITY_ITEMS:
        if item.lower() in titles_lower:
            priority.append(item)
            used.add(item.lower())

    # OG STW check
    has_og_stw = "rose team leader" in titles_lower
    if has_og_stw:
        used.add("rose team leader")

    # Special skins — ordered by _SPECIAL_SKINS definition
    special: list[str] = []
    for skin in _SPECIAL_SKINS:
        if skin.lower() in titles_lower and skin.lower() not in used:
            special.append(skin)
            used.add(skin.lower())

    # Cheap account items — only if price < 25
    cheap: list[str] = []
    if account.price < 25:
        for item in _CHEAP_ACCOUNT_ITEMS:
            if item.lower() in titles_lower and item.lower() not in used:
                label = "Reaper Axe" if item == "Reaper" else item
                cheap.append(label)
                used.add(item.lower())

    # Remaining cosmetics — original order from cosmetic_titles
    other: list[str] = []
    for title in account.cosmetic_titles:
        if title.lower() not in used:
            other.append(title)
            used.add(title.lower())

    return priority, has_og_stw, special, cheap, other


# -- Dynamic cosmetic list matching ------------------------------------------

CosmeticListConfig = list[dict[str, Any]]
"""Each dict has: slug, items, match_field (all from DB)."""


def _match_dynamic_lists(
    account: FortniteResolvedAccount,
    cosmetic_lists: CosmeticListConfig,
) -> dict[str, list[str]]:
    """Match account fields against user-defined cosmetic lists.

    Processes lists in the order given (caller sorts by priority).
    Items matched by earlier lists are excluded from later ones (dedup).

    Returns a dict mapping slug -> matched items, plus a ``remaining``
    key with all unmatched items from cosmetic_titles.
    """
    result: dict[str, list[str]] = {}
    used: set[str] = set()

    for cl in cosmetic_lists:
        slug = cl["slug"]
        items_to_match: list[str] = cl.get("items", [])
        match_field: str = cl.get("match_field", "cosmetic_titles")

        # Get the source values from the account
        source_values: list[str] = getattr(account, match_field, [])
        if not isinstance(source_values, list):
            source_values = []

        source_lower = {v.lower() for v in source_values}
        matched: list[str] = []

        for item in items_to_match:
            if item.lower() in source_lower and item.lower() not in used:
                matched.append(item)
                used.add(item.lower())

        result[slug] = matched

    # Remaining: items from cosmetic_titles not claimed by any list
    remaining: list[str] = []
    for title in account.cosmetic_titles:
        if title.lower() not in used:
            remaining.append(title)
            used.add(title.lower())
    result["remaining"] = remaining

    return result


def build_fortnite_context(
    account: FortniteResolvedAccount,
    request: PipelineRequest,
    media: MediaBundle,
    *,
    cosmetic_lists: CosmeticListConfig | None = None,
) -> dict[str, Any]:
    """Build a flat context dict from a resolved Fortnite account.

    Includes all dataclass fields plus computed/derived values.

    When *cosmetic_lists* is provided (from DB), dynamic list matching
    is used instead of the legacy hardcoded buckets.  Each list's slug
    becomes a context key with the matched items as value.
    """
    skip = {"credentials", "cosmetic_items", "preview_urls"}
    context: dict[str, Any] = {
        field.name: getattr(account, field.name)
        for field in dc_fields(account)
        if field.name not in skip
    }

    # Dynamic lists from DB take precedence over legacy hardcoded buckets
    if cosmetic_lists:
        dynamic = _match_dynamic_lists(account, cosmetic_lists)
        context.update(dynamic)
    else:
        # Legacy fallback — hardcoded buckets
        priority, has_og_stw, special, cheap, other = _build_title_cosmetics(account)
        context.update({
            "priority_items": priority,
            "has_og_stw": has_og_stw,
            "special_skins": special,
            "cheap_items": cheap,
            "other_cosmetics": other,
        })

    context.update({
        "total_cosmetics": (
            account.skin_count + account.pickaxe_count
            + account.dance_count + account.glider_count
        ),
        "psn_linkable_label": "Yes" if account.psn_linkable else "No",
        "xbox_linkable_label": "Yes" if account.xbox_linkable else "No",
        "email_access_label": "Yes" if account.has_email_access else "No",
        "platform_label": _build_platform_label(account),
        "vbucks_display": account.v_bucks if (
            account.platform == "EpicPC" and account.v_bucks >= 500
        ) else 0,
        "album_url": media.album_url or "",
        "is_stock": request.kind == ListingKind.STOCK,
    })

    return context
