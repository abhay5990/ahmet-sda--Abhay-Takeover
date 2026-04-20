"""Eldorado image upload helpers owned by payload_pipeline.

Uses the ``MarketplaceImageUploader`` protocol — the pipeline never
calls vendor-specific methods (``response.ok``, ``response.data``, etc.)
directly.  The consuming project provides an adapter.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ..shared.image_processing import normalize_image_for_upload, shrink_image

if TYPE_CHECKING:
    from ..core.contracts import MarketplaceImageUploader

logger = logging.getLogger(__name__)


def upload_images_to_eldorado(
    image_paths: list[str],
    uploader: MarketplaceImageUploader,
    max_retries: int = 2,
) -> list[str]:
    """Upload prepared local images via the injected uploader protocol.

    The *uploader* must satisfy ``MarketplaceImageUploader``:
    ``upload_image(file_path) -> list[str] | None``.
    """
    if not image_paths:
        return []

    logger.info("Starting Eldorado image upload for %s images", len(image_paths))
    formatted_paths: list[str] = []

    for index, image_path in enumerate(image_paths, start=1):
        image_path_str = str(image_path)
        image_name = Path(image_path_str).name

        if not Path(image_path_str).exists():
            raise FileNotFoundError(f"Image file not found: {image_path_str}")

        normalized_path = normalize_image_for_upload(image_path_str, output_format="PNG")
        resized_path = shrink_image(normalized_path)
        upload_path = str(resized_path or normalized_path)

        success = False
        last_error: str | None = None

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(
                    "[%s/%s] Uploading image (attempt %s/%s): %s",
                    index, len(image_paths), attempt, max_retries, image_name,
                )

                result = uploader.upload_image(upload_path)

                if result is not None:
                    logger.info(
                        "[%s/%s] Upload successful: received %s paths for %s",
                        index, len(image_paths), len(result), image_name,
                    )
                    formatted_paths.extend(result)
                    success = True
                    break

                last_error = "upload returned None"
                if attempt < max_retries:
                    logger.warning(
                        "[%s/%s] Upload failed (attempt %s/%s). Retrying.",
                        index, len(image_paths), attempt, max_retries,
                    )

            except Exception as exc:
                last_error = str(exc)
                if attempt < max_retries:
                    logger.warning(
                        "[%s/%s] Exception during upload (attempt %s/%s): %s. Retrying.",
                        index, len(image_paths), attempt, max_retries, exc,
                    )
                else:
                    logger.error(
                        "[%s/%s] Exception after %s attempts: %s",
                        index, len(image_paths), max_retries, exc,
                    )

        if not success:
            raise RuntimeError(
                f"Image upload failed for {image_name} after {max_retries} attempts: {last_error}"
            )

    logger.info("All images uploaded successfully. Total formatted paths: %s", len(formatted_paths))
    return formatted_paths
