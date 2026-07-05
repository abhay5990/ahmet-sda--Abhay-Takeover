"""Template context builder for Roblox listing composition.

Provides build_roblox_context() — a flat field→value dict used by
RobloxComposer when rendering {field_name} placeholder templates.
"""

from __future__ import annotations

from dataclasses import fields as dc_fields
from datetime import datetime, timezone
from typing import Any

from .....core.contracts import MediaBundle, PipelineRequest
from .....core.enums import ListingKind
from ..models import RobloxResolvedAccount


def build_roblox_context(
    account: RobloxResolvedAccount,
    request: PipelineRequest,
    media: MediaBundle,
) -> dict[str, Any]:
    """Build a flat context dict from a resolved Roblox account.

    Includes all dataclass fields plus computed/derived values.
    """
    # Start with all dataclass fields (except credentials)
    context: dict[str, Any] = {
        field.name: getattr(account, field.name)
        for field in dc_fields(account)
        if field.name != "credentials"
    }

    # Add computed fields
    context.update({
        "profile_url": (
            f"www.roblox.com/users/{account.roblox_id}/profile"
            if account.roblox_id
            else ""
        ),
        "register_date": _format_register_date(account.register_date),
        "register_year": _register_year(account.register_date),
        "letter_tag": _letter_tag(account.username),
        "letter_label": _letter_label(account.username),
        "age_verified_label": "Yes" if account.age_verified else "No",
        "inventory_price_int": int(account.inventory_price),
        "ugc_limited_price_int": int(account.ugc_limited_price),
        "album_url": media.album_url or "",
        "is_stock": request.kind == ListingKind.STOCK,
    })

    return context


def _letter_tag(username: str) -> str:
    if username and len(username) == 3:
        return "3 Letter, "
    if username and len(username) == 4:
        return "4 Letter, "
    return ""


def _letter_label(username: str) -> str:
    if username and len(username) == 3:
        return "3 Letter"
    if username and len(username) == 4:
        return "4 Letter"
    return ""


def _format_register_date(timestamp: int) -> str:
    try:
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return "Unknown"


def _register_year(timestamp: int) -> str:
    try:
        return str(datetime.fromtimestamp(int(timestamp), tz=timezone.utc).year)
    except Exception:
        return "Unknown"
