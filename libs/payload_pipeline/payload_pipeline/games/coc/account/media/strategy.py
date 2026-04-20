"""Media strategy for Clash of Clans — generates hero/troop/spell grid images."""

from __future__ import annotations

import logging

from ..models import CocResolvedAccount
from .....core import context_keys as ctx
from .....core.contracts import PipelineRequest
from .....shared.paths import default_media_output_dir
from .image_renderer import CocImageRenderer

logger = logging.getLogger(__name__)


class CocMediaStrategy:
    """Generate CoC account images from resolved data."""

    def __init__(self, renderer: CocImageRenderer | None = None) -> None:
        self._renderer = renderer

    def prepare(
        self, subject: CocResolvedAccount, request: PipelineRequest
    ) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []
        if (
            not subject.heroes
            and not subject.troops
            and not subject.spells
        ):
            return []

        renderer = self._renderer or CocImageRenderer()
        output_dir = self._resolve_output_dir(request, subject.item_id)

        try:
            return renderer.render(
                heroes=subject.heroes,
                troops=subject.troops,
                spells=subject.spells,
                hero_equipment=subject.hero_equipment,
                super_troops=subject.super_troops,
                player_tag=subject.player_tag,
                output_dir=output_dir,
            )
        except Exception as exc:
            logger.warning("CoC media generation failed for item %s: %s", subject.item_id, exc)
            return []

    def _resolve_output_dir(self, request: PipelineRequest, item_id: str) -> str:
        configured = request.context.get(ctx.MEDIA_OUTPUT_DIR)
        if isinstance(configured, str) and configured.strip():
            return configured
        suffix = item_id.strip() or "preview"
        return default_media_output_dir("clash-of-clans", suffix=suffix)
