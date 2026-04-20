"""Media strategy for Clash Royale — generates a card grid image."""

from __future__ import annotations

import logging

from ..models import CrResolvedAccount
from .....core import context_keys as ctx
from .....core.contracts import PipelineRequest
from .....shared.paths import default_media_output_dir
from .image_renderer import CrImageRenderer

logger = logging.getLogger(__name__)


class CrMediaStrategy:
    """Generate a local card grid image from resolved Clash Royale data."""

    def __init__(self, renderer: CrImageRenderer | None = None) -> None:
        self._renderer = renderer

    def prepare(
        self, subject: CrResolvedAccount, request: PipelineRequest
    ) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []
        if not subject.cards_data:
            return []

        renderer = self._renderer or CrImageRenderer()
        output_dir = self._resolve_output_dir(request, subject.item_id)
        output_path = f"{output_dir}/{subject.item_id}_cards.png"

        try:
            result = renderer.render(subject.cards_data, output_path)
            return [result] if result else []
        except Exception as exc:
            logger.warning("CR media generation failed for item %s: %s", subject.item_id, exc)
            return []

    def _resolve_output_dir(self, request: PipelineRequest, item_id: str) -> str:
        configured = request.context.get(ctx.MEDIA_OUTPUT_DIR)
        if isinstance(configured, str) and configured.strip():
            return configured
        suffix = item_id.strip() or "preview"
        return default_media_output_dir("clash-royale", suffix=suffix)
