"""Media generation for Fortnite using LZT previews, Imgur albums, or local grid rendering."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image

from ..models import FortniteResolvedAccount
from .grid_renderer import FortniteGridRenderer
from .....core import context_keys as ctx
from .....core.contracts import PipelineRequest
from .....shared.imgur_downloader import download_album
from .....shared.lzt_image_fetcher import LztImageFetcher
from .....shared.media_policy import MediaSource, media_source_order
from .....shared.paths import default_media_output_dir

logger = logging.getLogger(__name__)

_FORTNITE_CATEGORIES = ("skins", "pickaxes", "dances", "gliders")


class FortnitePreviewDownloader:
    """Download Fortnite preview images via the injected LZT image fetcher."""

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
        """Ensure the saved file is a valid PNG with a predictable colour mode."""
        image = Image.open(path)
        image.load()
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA")
        image.save(path, format="PNG", optimize=True)


class FortniteMediaStrategy:
    """Prepare local preview images before optional external publication."""

    def __init__(
        self,
        downloader: FortnitePreviewDownloader | None = None,
        renderer: FortniteGridRenderer | None = None,
    ) -> None:
        self._downloader = downloader
        self._renderer = renderer

    def prepare(self, subject: FortniteResolvedAccount, request: PipelineRequest) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []

        output_dir = self._resolve_output_dir(request, subject.item_id)

        # Manual accounts: download from Imgur album first
        if subject.manual_images:
            paths = self._download_imgur(subject.manual_images, request, output_dir)
            if paths:
                return paths

        # Standard flow: LZT or generated
        for source in media_source_order(request):
            paths = (
                self._render_generated(subject, output_dir)
                if source is MediaSource.GENERATED
                else self._download_lzt(subject, request, output_dir)
            )
            if paths:
                return paths

        return []

    def _render_generated(self, subject: FortniteResolvedAccount, output_dir: str) -> list[str]:
        if not subject.cosmetic_items:
            return []

        renderer = self._renderer or FortniteGridRenderer()
        try:
            return renderer.render_all(subject.cosmetic_items, output_dir)
        except Exception as exc:
            logger.warning(
                "Fortnite grid rendering failed for item %s: %s",
                subject.item_id,
                exc,
            )
            return []

    def _download_lzt(
        self,
        subject: FortniteResolvedAccount,
        request: PipelineRequest,
        output_dir: str,
    ) -> list[str]:
        if not subject.preview_urls:
            return []

        image_fetcher = request.context.get(ctx.LZT_IMAGE_FETCHER)
        fetcher = LztImageFetcher(image_fetcher)
        downloader = self._downloader or FortnitePreviewDownloader(fetcher)
        try:
            return downloader.download(
                subject.preview_urls,
                output_dir,
                item_id=subject.item_id,
            )
        except Exception as exc:
            logger.warning(
                "Fortnite LZT media download failed for item %s: %s",
                subject.item_id,
                exc,
            )
            return []

    def _download_imgur(
        self,
        album_url: str,
        request: PipelineRequest,
        output_dir: str,
    ) -> list[str]:
        client_id = request.context.get(ctx.IMGUR_CLIENT_ID)
        if not client_id:
            logger.warning("No imgur_client_id in context, skipping Imgur download")
            return []

        try:
            return download_album(album_url, output_dir, client_id=client_id)
        except Exception as exc:
            logger.warning("Imgur album download failed for %s: %s", album_url, exc)
            return []

    def _resolve_output_dir(self, request: PipelineRequest, item_id: str) -> str:
        configured = request.context.get(ctx.MEDIA_OUTPUT_DIR)
        if isinstance(configured, str) and configured.strip():
            return configured

        suffix = item_id.strip() or "preview"
        return default_media_output_dir("fortnite", suffix=suffix)
