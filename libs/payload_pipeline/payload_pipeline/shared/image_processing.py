"""Image normalization and resize helpers owned by payload_pipeline."""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

from PIL import Image


def normalize_image_for_upload(path: str, output_format: str = "PNG") -> str:
    """Normalize an image into a predictable upload format."""

    path_obj = Path(path)

    try:
        image = Image.open(path)
        image.load()

        if image.mode in ("RGBA", "LA", "P"):
            if output_format.upper() == "JPEG":
                background = Image.new("RGB", image.size, (255, 255, 255))
                if image.mode == "RGBA":
                    background.paste(image, mask=image.getchannel("A"))
                elif image.mode == "P":
                    rgba = image.convert("RGBA")
                    background.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    rgba = image.convert("RGBA")
                    background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            elif output_format.upper() == "PNG" and image.mode != "RGBA":
                image = image.convert("RGB")
        elif image.mode != "RGB":
            image = image.convert("RGB")

        extension = ".png" if output_format.upper() == "PNG" else ".jpg"
        normalized_path = path_obj.parent / f"{path_obj.stem}_normalized{extension}"

        if output_format.upper() == "PNG":
            image.save(normalized_path, format="PNG", optimize=True)
        else:
            image.save(normalized_path, format="JPEG", quality=95, optimize=True)

        return str(normalized_path)
    except Exception as exc:
        logger.debug("Image normalization failed for %s: %s", path, exc)
        return path


def shrink_image(path: str, target_mb: float = 9.8, tolerance_mb: float = 0.05) -> str | None:
    """Shrink an image in place when it exceeds the upload size budget."""

    target_limit_mb = 10.0
    min_quality = 40
    max_quality = 95
    downscale_step = 0.92
    min_side = 128

    if _bytes_to_mb(os.path.getsize(path)) <= target_limit_mb:
        return None

    image = Image.open(path)
    image.load()

    if image.mode in ("RGBA", "LA"):
        background = Image.new("RGB", image.size, (255, 255, 255))
        rgba = image.convert("RGBA")
        background.paste(rgba, mask=rgba.getchannel("A"))
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    effective_target = target_mb + tolerance_mb
    current_image = image
    result = _best_quality_under_target(
        current_image,
        target_mb_limit=effective_target,
        min_quality=min_quality,
        max_quality=max_quality,
    )

    while result is None:
        width, height = current_image.size
        new_width = int(width * downscale_step)
        new_height = int(height * downscale_step)

        if new_width < min_side or new_height < min_side:
            blob = _encode_jpeg_bytes(current_image, min_quality)
            with open(path, "wb") as handle:
                handle.write(blob)
            return path

        current_image = current_image.resize((new_width, new_height), Image.LANCZOS)
        result = _best_quality_under_target(
            current_image,
            target_mb_limit=effective_target,
            min_quality=min_quality,
            max_quality=max_quality,
        )

    _, _, blob = result
    with open(path, "wb") as handle:
        handle.write(blob)

    return path


def _best_quality_under_target(
    image: Image.Image,
    *,
    target_mb_limit: float,
    min_quality: int,
    max_quality: int,
) -> tuple[int, int, bytes] | None:
    low = min_quality
    high = max_quality
    target_bytes = int(target_mb_limit * 1024 * 1024)
    best_result: tuple[int, int, bytes] | None = None

    while low <= high:
        mid = (low + high) // 2
        blob = _encode_jpeg_bytes(image, mid)
        size = len(blob)

        if size <= target_bytes:
            best_result = (size, mid, blob)
            low = mid + 1
        else:
            high = mid - 1

    return best_result


def _encode_jpeg_bytes(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(
        buffer,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=True,
        subsampling="4:2:0",
    )
    return buffer.getvalue()


def _bytes_to_mb(value: int) -> float:
    return value / (1024 * 1024)
