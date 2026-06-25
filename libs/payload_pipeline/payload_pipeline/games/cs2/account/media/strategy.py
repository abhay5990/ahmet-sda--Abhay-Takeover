"""Media strategy for CS2 — generates a Steam game-list grid image."""

from __future__ import annotations

import logging
from pathlib import Path

from ..models import CS2ResolvedAccount
from .....core import context_keys as ctx
from .....core.contracts import PipelineRequest
from .....shared.paths import default_cache_base_dir, default_media_output_dir
from .....shared.steam_game_grid import SteamGameGridRenderer

logger = logging.getLogger(__name__)

# Fallback when no games list is available — show CS2 only
_CS2_FALLBACK = {
    "appid": 730,
    "title": "Counter-Strike 2",
    "img": "https://cdn.akamai.steamstatic.com/steam/apps/730/header.jpg",
    "playtime_forever": 0,
}


class CS2MediaStrategy:
    """Generate a local game-list grid image from resolved CS2 data."""

    def __init__(self, renderer: SteamGameGridRenderer | None = None) -> None:
        self._renderer = renderer

    def prepare(
        self, subject: CS2ResolvedAccount, request: PipelineRequest
    ) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []

        # Manual entry: use user-selected override image
        override_path = self._media_override_path(request)
        if override_path:
            return [override_path]

        # Platform import: generate grid image
        renderer = self._renderer or SteamGameGridRenderer(
            cache_dir=default_cache_base_dir("counter-strike-2"),
        )

        output_dir = self._resolve_output_dir(request, subject.item_id)
        output_path = f"{output_dir}/cs2_{subject.item_id}.png"

        fallback = {**_CS2_FALLBACK, "playtime_forever": subject.hours_played}

        try:
            result = renderer.render(
                subject.games, output_path, fallback_game=fallback
            )
            return [result] if result else []
        except Exception as exc:
            logger.warning("CS2 media generation failed for item %s: %s", subject.item_id, exc)
            return []

    def _media_override_path(self, request: PipelineRequest) -> str:
        configured = request.context.get(ctx.MEDIA_OVERRIDE_PATH)
        if not isinstance(configured, str) or not configured.strip():
            return ""

        path = Path(configured)
        if path.is_file():
            return str(path)

        logger.warning("CS2 media override path does not exist: %s", configured)
        return ""

    def _resolve_output_dir(self, request: PipelineRequest, item_id: str) -> str:
        configured = request.context.get(ctx.MEDIA_OUTPUT_DIR)
        if isinstance(configured, str) and configured.strip():
            return configured
        suffix = item_id.strip() or "preview"
        return default_media_output_dir("counter-strike-2", suffix=suffix)
