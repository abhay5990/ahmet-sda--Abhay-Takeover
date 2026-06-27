"""Generated media strategy for GTA V accounts."""

from __future__ import annotations

import logging
from pathlib import Path

from .....core.capabilities import AUTO_GEN_AND_OVERRIDE, MediaCapabilities
from .....core.contracts import PipelineRequest
from .....core import context_keys as ctx
from .....core.enums import ListingKind
from .....shared.media_override import MediaOverrideMixin
from .....shared.paths import default_media_output_dir
from ..models import GtavResolvedAccount
from .image_renderer import GtavAccountCardRenderer, GtavCardData

logger = logging.getLogger(__name__)


class GtavMediaStrategy(MediaOverrideMixin):
    """Prepare one deterministic generated GTA V account card."""

    capabilities: MediaCapabilities = AUTO_GEN_AND_OVERRIDE

    def __init__(self, renderer: GtavAccountCardRenderer | None = None) -> None:
        self._renderer = renderer

    def prepare(self, subject: GtavResolvedAccount, request: PipelineRequest) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []

        override = self._check_override(request)
        if override is not None:
            return override

        renderer = self._renderer or GtavAccountCardRenderer()
        card_data = GtavCardData.from_account(
            subject,
            delivery_text=self._delivery_text(request),
        )
        output_dir = self._resolve_output_dir(request)
        output_path = Path(output_dir) / f"gtav_account_{renderer.fingerprint(card_data)}.png"

        if output_path.is_file():
            return [str(output_path)]

        try:
            return [renderer.render(card_data, output_path)]
        except Exception as exc:
            logger.warning("GTA V media generation failed for item %s: %s", subject.item_id, exc)
            return []

    def _resolve_output_dir(self, request: PipelineRequest) -> str:
        configured = request.context.get(ctx.MEDIA_OUTPUT_DIR)
        if isinstance(configured, str) and configured.strip():
            return configured
        return default_media_output_dir("grand-theft-auto-5", suffix="cards")

    def _delivery_text(self, request: PipelineRequest) -> str:
        return "MANUAL DELIVERY" if request.kind == ListingKind.DROPSHIPPING else "INSTANT DELIVERY"
