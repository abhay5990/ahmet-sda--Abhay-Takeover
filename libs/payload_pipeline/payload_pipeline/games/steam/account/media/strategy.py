"""Media strategy for Steam — generates a game-list grid image."""

from __future__ import annotations

import logging

from ..models import SteamResolvedAccount
from .....core import context_keys as ctx
from .....core.contracts import PipelineRequest
from .....shared.paths import default_cache_base_dir, default_media_output_dir
from .....shared.steam_game_grid import SteamGameGridRenderer

logger = logging.getLogger(__name__)


class SteamMediaStrategy:
    """Generate a local game-list grid image from resolved Steam data."""

    def __init__(self, renderer: SteamGameGridRenderer | None = None) -> None:
        self._renderer = renderer

    def prepare(
        self, subject: SteamResolvedAccount, request: PipelineRequest
    ) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []
        if not subject.games:
            return []

        renderer = self._renderer or SteamGameGridRenderer(
            cache_dir=default_cache_base_dir("steam"),
        )

        output_dir = self._resolve_output_dir(request, subject.item_id)
        output_path = f"{output_dir}/steam_{subject.item_id}.png"

        try:
            result = renderer.render(subject.games, output_path)
            return [result] if result else []
        except Exception as exc:
            logger.warning("Steam media generation failed for item %s: %s", subject.item_id, exc)
            return []

    def _resolve_output_dir(self, request: PipelineRequest, item_id: str) -> str:
        configured = request.context.get(ctx.MEDIA_OUTPUT_DIR)
        if isinstance(configured, str) and configured.strip():
            return configured
        suffix = item_id.strip() or "preview"
        return default_media_output_dir("steam", suffix=suffix)
