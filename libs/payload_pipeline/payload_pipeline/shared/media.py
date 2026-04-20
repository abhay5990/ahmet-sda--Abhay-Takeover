"""Shared media publishing helpers for payload_pipeline."""

from __future__ import annotations

from collections.abc import Sequence
import logging
from pathlib import Path
from ..core.contracts import AlbumUploader, ImageUploader, MediaBundle, PipelineRequest
from .uploads import upload_images_parallel


logger = logging.getLogger(__name__)


class NullMediaPublisher:
    """Default publisher that keeps generated files local."""

    def publish(
        self,
        local_paths: Sequence[str],
        request: PipelineRequest | None = None,
    ) -> MediaBundle:
        normalized = [str(Path(path)) for path in local_paths if path]
        return MediaBundle(local_paths=normalized)


class HostedMediaPublisher:
    """Upload generated media to shared hosts when credentials are configured.

    Both uploader instances must satisfy the pipeline protocols
    (``ImageUploader`` and ``AlbumUploader``).  The consuming project
    provides concrete implementations that wrap its SDK clients.

    Example::

        publisher = HostedMediaPublisher(
            dropbox_uploader=DropboxImageUploader(facade, credential),
            imageshack_processor=ImageShackAlbumUploader(facade, prefix),
        )
    """

    def __init__(
        self,
        *,
        dropbox_uploader: ImageUploader,
        imageshack_processor: AlbumUploader,
        strict: bool = False,
    ) -> None:
        self.strict = strict
        self._dropbox_uploader = dropbox_uploader
        self._imageshack_processor = imageshack_processor

    @property
    def dropbox_uploader(self):
        return self._dropbox_uploader

    @property
    def imageshack_processor(self):
        return self._imageshack_processor

    def publish(
        self,
        local_paths: Sequence[str],
        request: PipelineRequest | None = None,
    ) -> MediaBundle:
        valid_paths = [str(Path(path)) for path in local_paths if path and Path(path).exists()]
        if not valid_paths:
            return MediaBundle(local_paths=[str(Path(path)) for path in local_paths if path])

        try:
            external_urls, album_url = upload_images_parallel(
                self.dropbox_uploader,
                self.imageshack_processor,
                valid_paths,
            )
        except Exception as exc:
            if self.strict:
                raise
            logger.warning(
                "Hosted media publication failed for %s: %s",
                request.game if request else "unknown",
                exc,
            )
            return MediaBundle(local_paths=valid_paths)

        return MediaBundle(
            local_paths=valid_paths,
            external_urls=list(external_urls or []),
            album_url=album_url or None,
        )
