"""Template context builder for Genshin Impact listing composition.

Provides build_genshin_context() -- a flat field->value dict used by
GenshinComposer when rendering {field_name} placeholder templates.
"""

from __future__ import annotations

from dataclasses import fields as dc_fields
from typing import Any

from .title_generator import REGION_MAP
from .....core.contracts import MediaBundle, PipelineRequest
from .....core.enums import ListingKind
from ..models import GenshinResolvedAccount

_NOTABLE_4STAR_MIN_CONS = 4


def _char_with_cons(name: str, cons: int) -> str:
    if cons > 0:
        return f"{name} C{cons}"
    return name


def _hsr_with_eidolon(name: str, eidolon: int) -> str:
    if eidolon > 0:
        return f"{name} E{eidolon}"
    return name


def build_genshin_context(
    account: GenshinResolvedAccount,
    request: PipelineRequest,
    media: MediaBundle,
) -> dict[str, Any]:
    """Build a flat context dict from a resolved Genshin account.

    Includes all dataclass fields plus computed/derived values.
    """
    skip = {
        "credentials", "genshin_characters", "honkai_characters",
        "zenless_characters",
    }
    context: dict[str, Any] = {
        field.name: getattr(account, field.name)
        for field in dc_fields(account)
        if field.name not in skip
    }

    # Region code
    context["region_code"] = REGION_MAP.get(
        account.region, account.region.upper() or "UNK",
    )

    # 5-star characters with constellation notation
    context["genshin_5star_with_cons"] = [
        _char_with_cons(c.name, c.constellation)
        for c in account.genshin_characters
        if c.rarity == 5 and c.name != "Traveler"
    ]

    # Notable 4-star constellations (C4+)
    notable = sorted(
        (c for c in account.genshin_characters
         if c.rarity == 4 and c.constellation >= _NOTABLE_4STAR_MIN_CONS),
        key=lambda c: c.constellation,
        reverse=True,
    )
    context["notable_4star_cons"] = [
        _char_with_cons(c.name, c.constellation) for c in notable
    ]

    # HSR 5-star with eidolons
    context["honkai_5star_with_eidolons"] = [
        _hsr_with_eidolon(c.name, c.eidolon)
        for c in account.honkai_characters
        if c.rarity == 5 and c.name != "Trailblazer"
    ]

    # HSR summary tag
    if account.honkai_level > 0:
        context["hsr_summary"] = f"HSR TL{account.honkai_level}"
    else:
        context["hsr_summary"] = ""

    # Media
    context["album_url"] = media.album_url or ""
    context["is_stock"] = request.kind == ListingKind.STOCK

    return context
