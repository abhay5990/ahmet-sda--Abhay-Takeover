"""PlayerAuctions payload pipeline — routes to game-specific row builders.

All PA-specific knowledge lives here:
- Game routing (valorant → build_valorant_row, etc.)
- Excel column template and XLSX generation
- Common field helpers (fake personal info, delivery fields)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.posting.pipeline.playerauctions.common import rows_to_xlsx  # noqa: F401


# Game slug → row builder function
_GAME_BUILDERS: dict[str, Any] = {}


def _register_game_builders() -> None:
    """Lazily import and register game-specific row builders."""
    from apps.posting.pipeline.playerauctions import valorant as _valo

    _GAME_BUILDERS['valorant'] = _valo.build_row
    # TODO: register additional games as builders are implemented
    # _GAME_BUILDERS['fortnite'] = fortnite.build_row
    # _GAME_BUILDERS['lol'] = lol.build_row


def build_pa_payload(
    *,
    game,
    owned_product,
    sources: dict,
    final_price: Decimal,
    sub_platform: str,
) -> tuple[dict[str, Any], str]:
    """Route to game-specific PA row builder.

    Returns (excel_row_dict, mode='excel_row').
    The dict is a flat mapping of Excel column → value ready for rows_to_xlsx().
    """
    if not _GAME_BUILDERS:
        _register_game_builders()

    game_slug = game.slug if hasattr(game, 'slug') else str(game).lower()
    builder = _GAME_BUILDERS.get(game_slug)

    if builder is None:
        # Fallback: generic row with minimal fields
        from apps.posting.pipeline.playerauctions.common import build_generic_row
        row = build_generic_row(
            game=game,
            owned_product=owned_product,
            sources=sources,
            final_price=final_price,
            sub_platform=sub_platform,
        )
    else:
        row = builder(
            game=game,
            owned_product=owned_product,
            sources=sources,
            final_price=final_price,
            sub_platform=sub_platform,
        )

    return row, 'excel_row'
