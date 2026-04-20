"""Upload helpers owned by payload_pipeline.

Uses a direct ThreadPoolExecutor instead of asyncio so the function
is safe to call from both sync contexts and existing event loops.
"""

from __future__ import annotations

import logging
from ..core.contracts import AlbumUploader, ImageUploader
from .concurrency import get_executor

logger = logging.getLogger(__name__)

_UPLOAD_TIMEOUT = 120  # seconds per upload task


def upload_images_parallel(
    dropbox_uploader: ImageUploader,
    imageshack_processor: AlbumUploader,
    image_paths: list[str],
) -> tuple[list[str], str]:
    """Upload images to Dropbox and ImageShack in parallel using threads."""
    if not image_paths:
        return [], ""

    executor = get_executor()
    dropbox_future = executor.submit(dropbox_uploader.upload_images, image_paths)
    imageshack_future = executor.submit(
        imageshack_processor.upload_album_from_paths, image_paths,
    )

    dropbox_links: list[str] = []
    album_url: str = ""

    try:
        result = dropbox_future.result(timeout=_UPLOAD_TIMEOUT)
        if isinstance(result, list):
            dropbox_links = result
    except Exception as exc:
        logger.warning("Dropbox upload failed: %s", exc)

    try:
        result = imageshack_future.result(timeout=_UPLOAD_TIMEOUT)
        if isinstance(result, str):
            album_url = result
    except Exception as exc:
        logger.warning("ImageShack upload failed: %s", exc)

    return dropbox_links, album_url
