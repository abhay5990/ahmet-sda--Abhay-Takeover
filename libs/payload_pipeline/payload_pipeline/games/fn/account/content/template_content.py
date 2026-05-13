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


def build_fortnite_context(
    account: FortniteResolvedAccount,
    request: PipelineRequest,
    media: MediaBundle,
) -> dict[str, Any]:
    """Build a flat context dict from a resolved Fortnite account.

    Includes all dataclass fields plus computed/derived values.
    """
    skip = {"credentials", "cosmetic_items", "preview_urls"}
    context: dict[str, Any] = {
        field.name: getattr(account, field.name)
        for field in dc_fields(account)
        if field.name not in skip
    }

    context.update({
        "total_cosmetics": (
            account.skin_count + account.pickaxe_count
            + account.dance_count + account.glider_count
        ),
        "psn_linkable_label": "Yes" if account.psn_linkable else "No",
        "xbox_linkable_label": "Yes" if account.xbox_linkable else "No",
        "email_access_label": "Yes" if account.has_email_access else "No",
        "album_url": media.album_url or "",
        "is_stock": request.kind == ListingKind.STOCK,
    })

    return context
