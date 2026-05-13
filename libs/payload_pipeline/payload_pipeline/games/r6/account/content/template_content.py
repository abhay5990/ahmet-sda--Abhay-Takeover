"""Template context builder for R6 listing composition.

Provides build_r6_context() — a flat field→value dict used by
R6Composer when rendering {field_name} placeholder templates.
"""

from __future__ import annotations

from dataclasses import fields as dc_fields
from typing import Any

from .....core.contracts import MediaBundle, PipelineRequest
from .....core.enums import ListingKind
from ..models import R6ResolvedAccount


def build_r6_context(
    account: R6ResolvedAccount,
    request: PipelineRequest,
    media: MediaBundle,
) -> dict[str, Any]:
    """Build a flat context dict from a resolved R6 account.

    Includes all dataclass fields plus computed/derived values.
    """
    skip = {"credentials", "inventory"}
    context: dict[str, Any] = {
        field.name: getattr(account, field.name)
        for field in dc_fields(account)
        if field.name not in skip
    }

    inv = account.inventory
    context.update({
        # Inventory breakdown counts
        "glacier_count": inv.glaciers.count,
        "glacier_items": inv.glaciers.items,
        "black_ice_count": inv.black_ices.count,
        "black_ice_items": inv.black_ices.items,
        "dust_line_count": inv.dust_lines.count,
        "dust_line_items": inv.dust_lines.items,
        "universal_count": inv.universals.count,
        "universal_items": inv.universals.items,
        "seasonal_count": inv.seasonals.count,
        "seasonal_items": inv.seasonals.items,
        "pro_league_old_count": inv.pro_leagues_old.count,
        "pro_league_old_items": inv.pro_leagues_old.items,
        "pro_league_new_count": inv.pro_leagues_new.count,
        "pro_league_new_items": inv.pro_leagues_new.items,
        "pilot_program_count": inv.pilot_program.count,
        "pilot_program_items": inv.pilot_program.items,
        "elite_count": inv.elites.count,
        "elite_items": inv.elites.items,
        "legendary_skin_count": inv.legendary_skins.count,
        "legendary_skin_items": inv.legendary_skins.items,
        "ranked_charm_count": inv.ranked_charms.count,
        "ranked_charm_items": inv.ranked_charms.items,
        "racer_count": inv.racer_count(),
        "racer_items": inv.racer_items(),
        "has_inventory_data": inv.has_data,
        # Computed properties
        "ranked_ready": account.ranked_ready,
        "available_platforms": account.available_platforms,
        "linkable_platforms": account.linkable_platforms,
        "ownership_text": account.ownership_text,
        "platform_type_text": account.platform_type_text,
        # Media & request
        "album_url": media.album_url or "",
        "is_stock": request.kind == ListingKind.STOCK,
    })

    return context
