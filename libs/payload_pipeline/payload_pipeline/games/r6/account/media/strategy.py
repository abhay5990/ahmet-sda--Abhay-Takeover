"""Media generation for R6 using typed LZT and tracker image generators."""

from __future__ import annotations

import logging
from pathlib import Path

from .image_renderer import _DEFAULT_R6_OUTPUT_DIR
from .lzt_image_generator import R6LztImageGenerator, R6LztImageInput
from .tracker_image_generator import R6TrackerImageGenerator, R6TrackerImageInput

from ..models import R6ResolvedAccount
from ..sources.lzt import R6LztSourceAdapter
from ..sources.tracker import R6TrackerSourceAdapter
from .....core.contracts import PipelineRequest
from .....core import context_keys as ctx


logger = logging.getLogger(__name__)


class R6MediaStrategy:
    """Prepare local preview images before any optional external publication."""

    def __init__(self) -> None:
        self.lzt_source = R6LztSourceAdapter()
        self.tracker_source = R6TrackerSourceAdapter()
        self.lzt_image_generator = R6LztImageGenerator()
        self.tracker_image_generator = R6TrackerImageGenerator()

    def prepare(self, subject: R6ResolvedAccount, request: PipelineRequest) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []

        output_dir = self._resolve_output_dir(request)

        try:
            paths = self._prepare_local_images(subject, request, output_dir)
        except Exception as exc:
            logger.warning("R6 media generation failed: %s", exc)
            return []

        return [str(Path(path)) for path in paths if path]

    def _prepare_local_images(
        self,
        subject: R6ResolvedAccount,
        request: PipelineRequest,
        output_dir: str,
    ) -> list[str]:
        lzt_source = self.lzt_source.parse(request.source("lzt"))
        tracker_source = self.tracker_source.parse(request.source("tracker"))

        if lzt_source is not None and tracker_source is not None:
            product_id = self._resolve_product_id(
                subject=subject,
                lzt_source=lzt_source,
                tracker_source=tracker_source,
            )
            tracker_input = R6TrackerImageInput.from_source(tracker_source, product_id=product_id)
            lzt_input = R6LztImageInput.from_source(lzt_source, product_id=product_id)
            paths = self.tracker_image_generator.generate_skin_images(
                tracker_input,
                output_folder=output_dir,
            )
            operator_path = self.lzt_image_generator.generate_operator_image(
                lzt_input,
                output_folder=output_dir,
            )
            if operator_path:
                paths.append(operator_path)
            return paths

        if tracker_source is not None:
            tracker_input = R6TrackerImageInput.from_source(tracker_source)
            return self.tracker_image_generator.generate_account_images(
                tracker_input,
                output_folder=output_dir,
            )

        if lzt_source is not None:
            lzt_input = R6LztImageInput.from_source(lzt_source)
            return self.lzt_image_generator.generate_account_images(lzt_input, output_folder=output_dir)

        return []

    def _resolve_output_dir(self, request: PipelineRequest) -> str:
        configured = request.context.get(ctx.MEDIA_OUTPUT_DIR)
        if isinstance(configured, str) and configured.strip():
            return configured
        return _DEFAULT_R6_OUTPUT_DIR

    def _resolve_product_id(self, *, subject: R6ResolvedAccount, lzt_source, tracker_source) -> str:
        if lzt_source.item_id:
            return lzt_source.item_id
        if lzt_source.uplay_id:
            return lzt_source.uplay_id
        if tracker_source.user_id:
            return tracker_source.user_id
        if tracker_source.masked_id:
            return tracker_source.masked_id
        if tracker_source.username:
            return tracker_source.username
        return subject.item_id if subject.item_id else "tracker"
