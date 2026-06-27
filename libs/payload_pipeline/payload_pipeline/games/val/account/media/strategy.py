"""Media generation for Valorant using LZT previews or generated media."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from ..models import ValorantResolvedAccount
from .....core.capabilities import OVERRIDE_ONLY, MediaCapabilities
from .....core import context_keys as ctx
from .....core.contracts import PipelineRequest
from .....shared.lzt_image_fetcher import LztImageFetcher
from .....shared.media_override import MediaOverrideMixin
from .....shared.media_policy import MediaSource, media_source_order
from .....shared.paths import default_media_output_dir
from .image_renderer import ValorantImageRenderer

logger = logging.getLogger(__name__)

_VALORANT_CATEGORIES = ("weapons", "agents", "buddies")


class ValorantPreviewDownloader:
    """Download prepared Valorant preview images and save them locally."""

    def __init__(self, fetcher: LztImageFetcher | None = None) -> None:
        self.fetcher = fetcher or LztImageFetcher()

    def download(
        self,
        preview_urls: dict[str, str],
        output_dir: str,
        item_id: str = "",
    ) -> list[str]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        saved_paths: list[str] = []
        for category in _VALORANT_CATEGORIES:
            image_path = output_path / f"valorant_{category}.png"

            ok = self.fetcher.fetch_to_file(
                category=category,
                item_id=item_id,
                output_path=image_path,
            )
            if ok:
                self._normalize_image(image_path)
                saved_paths.append(str(image_path))

        return saved_paths

    @staticmethod
    def _normalize_image(path: Path) -> None:
        """Ensure the saved file is a valid PNG with a predictable colour mode."""
        image = Image.open(path)
        image.load()
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA")
        image.save(path, format="PNG", optimize=True)


class ValorantMediaStrategy(MediaOverrideMixin):
    """Prepare local preview images before optional external publication."""

    capabilities: MediaCapabilities = OVERRIDE_ONLY

    def __init__(
        self,
        downloader: ValorantPreviewDownloader | None = None,
        renderer: ValorantImageRenderer | None = None,
    ) -> None:
        self._downloader = downloader
        self._renderer = renderer

    def prepare(self, subject: ValorantResolvedAccount, request: PipelineRequest) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []

        override = self._check_override(request)
        if override is not None:
            return override

        output_dir = self._resolve_output_dir(request, subject.item_id)
        for source in media_source_order(request):
            paths = (
                self._render_generated(subject, output_dir)
                if source is MediaSource.GENERATED
                else self._download_lzt(subject, request, output_dir)
            )
            if paths:
                return paths

        return []

    def _render_generated(
        self,
        subject: ValorantResolvedAccount,
        output_dir: str,
    ) -> list[str]:
        if not subject.skin_names and not subject.agent_names and not subject.buddy_names:
            return []

        renderer = self._renderer or ValorantImageRenderer()
        try:
            return renderer.render(
                skin_names=subject.skin_names,
                agent_names=subject.agent_names,
                buddy_names=subject.buddy_names,
                output_dir=output_dir,
                item_id=subject.item_id,
            )
        except Exception as exc:
            logger.warning(
                "Valorant generated media failed for item %s: %s",
                subject.item_id,
                exc,
            )
            return []

    def _download_lzt(
        self,
        subject: ValorantResolvedAccount,
        request: PipelineRequest,
        output_dir: str,
    ) -> list[str]:
        if not subject.preview_urls:
            return []

        image_fetcher = request.context.get(ctx.LZT_IMAGE_FETCHER)
        fetcher = LztImageFetcher(image_fetcher)
        downloader = self._downloader or ValorantPreviewDownloader(fetcher)
        try:
            return downloader.download(
                subject.preview_urls,
                output_dir,
                item_id=subject.item_id,
            )
        except Exception as exc:
            logger.warning(
                "Valorant LZT media download failed for item %s: %s",
                subject.item_id,
                exc,
            )
            return []

    def _resolve_output_dir(self, request: PipelineRequest, item_id: str) -> str:
        configured = request.context.get(ctx.MEDIA_OUTPUT_DIR)
        if isinstance(configured, str) and configured.strip():
            return configured

        suffix = item_id.strip() or "preview"
        return default_media_output_dir("valorant", suffix=suffix)
