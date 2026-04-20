"""Media strategy for Brawl Stars — generates brawler grid images."""

from __future__ import annotations

import logging

from ..models import BSResolvedAccount
from .....core import context_keys as ctx
from .....core.contracts import PipelineRequest
from .....shared.paths import default_media_output_dir
from .image_renderer import BSImageRenderer

logger = logging.getLogger(__name__)


class BSMediaStrategy:
    """Generate a local brawler grid image from resolved account data."""

    def __init__(self, renderer: BSImageRenderer | None = None) -> None:
        self._renderer = renderer

    def prepare(
        self, subject: BSResolvedAccount, request: PipelineRequest
    ) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []
        if not subject.brawlers:
            return []

        renderer = self._renderer or BSImageRenderer()
        output_dir = self._resolve_output_dir(request, subject.item_id)
        output_path = f"{output_dir}/Brawlers_{subject.item_id}.png"

        try:
            result = renderer.render(subject.brawlers, output_path)
            return [result] if result else []
        except Exception as exc:
            logger.warning("BS media generation failed for item %s: %s", subject.item_id, exc)
            return []

    def _resolve_output_dir(self, request: PipelineRequest, item_id: str) -> str:
        configured = request.context.get(ctx.MEDIA_OUTPUT_DIR)
        if isinstance(configured, str) and configured.strip():
            return configured
        suffix = item_id.strip() or "preview"
        return default_media_output_dir("brawl-stars", suffix=suffix)
