"""Template context builder for League of Legends listing composition.

Provides build_lol_context() — a flat field->value dict used by
LolComposer when rendering {field_name} placeholder templates.
"""

from __future__ import annotations

from dataclasses import fields as dc_fields
from typing import Any

from .....core.contracts import MediaBundle, PipelineRequest
from .....core.enums import ListingKind
from ..models import LolResolvedAccount
from .title_generator import PRIORITY_SKINS, match_notable_skins


# -- Dynamic cosmetic list matching ------------------------------------------

CosmeticListConfig = list[dict[str, Any]]
"""Each dict has: slug, items, match_field (all from DB)."""


def _match_dynamic_lists(
    account: LolResolvedAccount,
    cosmetic_lists: CosmeticListConfig,
) -> dict[str, list[str]]:
    """Match account fields against user-defined cosmetic lists.

    Processes lists in the order given (caller sorts by priority).
    Items matched by earlier lists are excluded from later ones (dedup).

    Returns a dict mapping slug -> matched items, plus a ``remaining``
    key with all unmatched items from skin_names.
    """
    result: dict[str, list[str]] = {}
    used: set[str] = set()

    for cl in cosmetic_lists:
        slug = cl["slug"]
        items_to_match: list[str] = cl.get("items", [])
        match_field: str = cl.get("match_field", "skin_names")

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

    # Remaining: items from skin_names not claimed by any list
    remaining: list[str] = []
    for name in account.skin_names:
        if name.lower() not in used:
            remaining.append(name)
            used.add(name.lower())
    result["remaining"] = remaining

    return result


def _build_legacy_skin_buckets(
    account: LolResolvedAccount,
) -> dict[str, Any]:
    """Split skin_names into priority-based buckets (legacy fallback).

    Returns context keys: notable_skins, other_skins.
    """
    notable = match_notable_skins(account.skin_names)
    notable_set = {s.lower() for s in notable}

    other: list[str] = []
    for name in account.skin_names:
        if name.lower() not in notable_set:
            other.append(name)

    return {
        "notable_skins": notable,
        "other_skins": other,
    }


def _format_region(region: str) -> str:
    """Clean region string for display (remove trailing numbers)."""
    import re
    if not region or region == "UNKNOWN":
        return "UNKNOWN"
    return re.sub(r"\d+", "", region)


def _format_champion_count(count: int) -> str:
    if count >= 160:
        return "All Champs"
    if count > 90:
        return f"Nearly All Champs ({count})"
    return f"{count} Champions"


def build_lol_context(
    account: LolResolvedAccount,
    request: PipelineRequest,
    media: MediaBundle,
    *,
    cosmetic_lists: CosmeticListConfig | None = None,
) -> dict[str, Any]:
    """Build a flat context dict from a resolved LOL account.

    Includes all dataclass fields plus computed/derived values.

    When *cosmetic_lists* is provided (from DB), dynamic list matching
    is used instead of the legacy hardcoded buckets.
    """
    skip = {"credentials", "champion_ids", "skin_ids"}
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
        context.update(_build_legacy_skin_buckets(account))

    # Computed fields
    context.update({
        "region_label": _format_region(account.region),
        "rank_label": account.rank or "Unranked",
        "champion_label": _format_champion_count(account.champion_count),
        "email_access_label": "Yes" if account.has_email_access else "No",
        "be_display": account.blue_essence if account.blue_essence > 5000 else 0,
        "oe_display": account.orange_essence if account.orange_essence > 3000 else 0,
        "rp_display": account.riot_points if account.riot_points > 500 else 0,
        "me_display": account.mythic_essence if account.mythic_essence >= 10 else 0,
        "total_essence": account.blue_essence + account.orange_essence,
        "album_url": media.album_url or "",
        "is_stock": request.kind == ListingKind.STOCK,
    })

    return context
