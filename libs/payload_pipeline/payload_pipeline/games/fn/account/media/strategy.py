"""Media generation for Fortnite using the LZT image API."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from ..models import FortniteResolvedAccount
from .....core import context_keys as ctx
from .....core.contracts import PipelineRequest
from .....shared.lzt_image_fetcher import LztImageFetcher
from .....shared.paths import default_media_output_dir

logger = logging.getLogger(__name__)

# Fortnite LZT image categories (pipeline name → used by ImageFetcher)
_FORTNITE_CATEGORIES = ("skins", "pickaxes", "dances", "gliders")


class FortnitePreviewDownloader:
    """Download Fortnite preview images via LZT API and save them locally."""

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
        for category in _FORTNITE_CATEGORIES:
            image_path = output_path / f"fortnite_{category}.png"

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
        """Ensure the saved file is a valid PNG with correct colour mode."""
        image = Image.open(path)
        image.load()
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA")
        image.save(path, format="PNG", optimize=True)


class FortniteMediaStrategy:
    """Prepare local preview images before optional external publication."""

    def __init__(self, downloader: FortnitePreviewDownloader | None = None) -> None:
        self._downloader = downloader

    def prepare(self, subject: FortniteResolvedAccount, request: PipelineRequest) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []

        image_fetcher = request.context.get(ctx.LZT_IMAGE_FETCHER)
        fetcher = LztImageFetcher(image_fetcher)
        downloader = self._downloader or FortnitePreviewDownloader(fetcher)

        output_dir = self._resolve_output_dir(request, subject.item_id)
        try:
            return downloader.download(
                subject.preview_urls, output_dir, item_id=subject.item_id,
            )
        except Exception as exc:
            logger.warning("Fortnite media generation failed for item %s: %s", subject.item_id, exc)
            return []

    def _resolve_output_dir(self, request: PipelineRequest, item_id: str) -> str:
        configured = request.context.get(ctx.MEDIA_OUTPUT_DIR)
        if isinstance(configured, str) and configured.strip():
            return configured

        suffix = item_id.strip() or "preview"
        return default_media_output_dir("fortnite", suffix=suffix)
