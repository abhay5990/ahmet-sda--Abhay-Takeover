"""Media strategy for League of Legends — generates champion/skin grid images."""

from __future__ import annotations

import logging

from ..models import LolResolvedAccount
from .....core import context_keys as ctx
from .....core.contracts import PipelineRequest
from .....shared.paths import default_media_output_dir
from .image_renderer import LolImageRenderer

logger = logging.getLogger(__name__)


class LolMediaStrategy:
    """Generate local champion and skin grid images from resolved LoL data."""

    def __init__(self, renderer: LolImageRenderer | None = None) -> None:
        self._renderer = renderer

    def prepare(
        self, subject: LolResolvedAccount, request: PipelineRequest
    ) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []
        if not subject.champion_ids and not subject.skin_ids:
            return []

        renderer = self._renderer or LolImageRenderer()
        output_dir = self._resolve_output_dir(request, subject.item_id)

        try:
            return renderer.render(
                subject.champion_ids,
                subject.skin_ids,
                output_dir,
                item_id=subject.item_id,
            )
        except Exception as exc:
            logger.warning("LoL media generation failed for item %s: %s", subject.item_id, exc)
            return []

    def _resolve_output_dir(self, request: PipelineRequest, item_id: str) -> str:
        configured = request.context.get(ctx.MEDIA_OUTPUT_DIR)
        if isinstance(configured, str) and configured.strip():
            return configured
        suffix = item_id.strip() or "preview"
        return default_media_output_dir("league-of-legends", suffix=suffix)
