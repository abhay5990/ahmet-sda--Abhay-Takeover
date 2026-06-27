"""Media strategy for Ubisoft Connect — generates a game-list grid image."""

from __future__ import annotations

import logging

from ..models import UbisoftResolvedAccount
from .....core.capabilities import OVERRIDE_ONLY, MediaCapabilities
from .....core import context_keys as ctx
from .....core.contracts import PipelineRequest
from .....shared.media_override import MediaOverrideMixin
from .....shared.paths import default_media_output_dir
from .image_renderer import UbisoftImageRenderer

logger = logging.getLogger(__name__)


class UbisoftMediaStrategy(MediaOverrideMixin):
    """Generate a local game-list grid image from resolved Ubisoft data."""

    capabilities: MediaCapabilities = OVERRIDE_ONLY

    def __init__(self, renderer: UbisoftImageRenderer | None = None) -> None:
        self._renderer = renderer

    def prepare(
        self, subject: UbisoftResolvedAccount, request: PipelineRequest
    ) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []

        override = self._check_override(request)
        if override is not None:
            return override

        if not subject.games:
            return []

        renderer = self._renderer or UbisoftImageRenderer()
        output_dir = self._resolve_output_dir(request, subject.item_id)
        output_path = f"{output_dir}/ubisoft_{subject.item_id}.png"

        try:
            result = renderer.render(subject.games, output_path)
            return [result] if result else []
        except Exception as exc:
            logger.warning("Ubisoft media generation failed for item %s: %s", subject.item_id, exc)
            return []

    def _resolve_output_dir(self, request: PipelineRequest, item_id: str) -> str:
        configured = request.context.get(ctx.MEDIA_OUTPUT_DIR)
        if isinstance(configured, str) and configured.strip():
            return configured
        suffix = item_id.strip() or "preview"
        return default_media_output_dir("ubisoft-connect", suffix=suffix)
