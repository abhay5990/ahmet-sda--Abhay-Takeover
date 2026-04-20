"""Brawl Stars brawler grid image renderer.

Generates a grid image of brawler icons with rarity-based background
colours and name labels — matching the output of the legacy
``src/games/games/bs/generators/image_generator.py`` exactly.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter

from .....shared.paths import default_cache_base_dir

logger = logging.getLogger(__name__)

# Rarity → RGBA background colour (matches legacy generator)
_RARITY_COLORS: dict[str, tuple[int, int, int, int]] = {
    "legendary": (255, 223, 0, 255),
    "mythic": (255, 0, 0, 255),
    "epic": (255, 0, 255, 255),
    "superrare": (0, 0, 255, 255),
    "rare": (0, 255, 0, 255),
    "common": (0, 255, 255, 255),
}
_DEFAULT_COLOR: tuple[int, int, int, int] = (255, 255, 255, 255)

# Grid layout constants (matches legacy generator)
_COLUMNS = 4
_FRAME_WIDTH = 190
_FRAME_HEIGHT = 75
_SPACING = 10
_TOP_PADDING = 10
_BOTTOM_PADDING = 10
_FONT_SIZE = 15

_CDN_URL_TEMPLATE = "https://media.brawltime.ninja/brawlers/{path}/model.webp?size=100"


class BSImageRenderer:
    """Render a brawler grid image from resolved Brawl Stars data."""

    def __init__(self, cache_dir: str | None = None) -> None:
        self._cache_dir = cache_dir or os.path.join(
            default_cache_base_dir("brawl-stars"), "brawlers"
        )
        os.makedirs(self._cache_dir, exist_ok=True)
        self._session = requests.Session()
        self._session.mount("https://", HTTPAdapter(pool_connections=5, pool_maxsize=10))
        self._session.mount("http://", HTTPAdapter(pool_connections=2, pool_maxsize=5))

    def render(
        self,
        brawlers: dict[str, Any],
        output_path: str,
    ) -> str | None:
        """Build the brawler grid and save it to *output_path*.

        Returns the output path on success, ``None`` on failure.
        """
        if not brawlers:
            logger.warning("No brawlers data — skipping image generation.")
            return None

        images: list[Image.Image] = []
        names: list[str] = []

        iterable = brawlers.values() if isinstance(brawlers, dict) else brawlers

        for brawler in iterable:
            if not isinstance(brawler, dict):
                continue
            name = str(brawler.get("name", "Unknown")).strip()
            path = str(brawler.get("path", "unknown")).strip()
            rarity = str(brawler.get("class", "common")).strip().lower()

            url = _CDN_URL_TEMPLATE.format(path=path)
            img = self._download_with_background(path, url, rarity)
            if img is not None:
                images.append(img)
                names.append(name)
            else:
                logger.warning("Could not load brawler image: %s", path)

        if not images:
            logger.error("No brawler images could be loaded.")
            return None

        merged = self._create_grid(images, names)
        if merged is None:
            logger.error("Grid creation failed.")
            return None

        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            merged.save(output_path, format="PNG")
            logger.info("Brawler grid saved: %s", output_path)
            return output_path
        except Exception as exc:
            logger.error("Failed to save brawler grid: %s", exc)
            return None

    # ── private helpers ───────────────────────────────────────────────

    def _download_with_background(
        self, brawler_path: str, url: str, rarity: str
    ) -> Image.Image | None:
        img = self._get_cached_image(brawler_path, url)
        if img is None:
            return None
        bg_color = _RARITY_COLORS.get(rarity, _DEFAULT_COLOR)
        background = Image.new("RGBA", img.size, bg_color)
        return Image.alpha_composite(background, img)

    def _get_cached_image(self, brawler_path: str, url: str) -> Image.Image | None:
        cache_file = os.path.join(self._cache_dir, f"{brawler_path}.webp")

        if os.path.exists(cache_file):
            return self._load_image(cache_file)

        if self._download_to_cache(url, cache_file):
            return self._load_image(cache_file)
        return None

    def _download_to_cache(self, url: str, cache_path: str) -> bool:
        try:
            resp = self._session.get(url, timeout=10)
            resp.raise_for_status()
            with open(cache_path, "wb") as f:
                f.write(resp.content)
            return True
        except Exception as exc:
            logger.warning("Image download failed %s: %s", url, exc)
            return False

    @staticmethod
    def _load_image(path: str) -> Image.Image | None:
        try:
            return Image.open(path).convert("RGBA")
        except Exception as exc:
            logger.warning("Failed to load cached image %s: %s", path, exc)
            return None

    @staticmethod
    def _create_grid(
        images: list[Image.Image],
        titles: list[str],
    ) -> Image.Image | None:
        if not images:
            return None

        total = len(images)
        rows = (total + _COLUMNS - 1) // _COLUMNS

        grid_w = _COLUMNS * (_FRAME_WIDTH + _SPACING)
        grid_h = rows * (_FRAME_HEIGHT + _SPACING) + _TOP_PADDING + _BOTTOM_PADDING

        merged = Image.new("RGBA", (grid_w, grid_h), (0, 0, 0, 0))

        try:
            font = ImageFont.truetype("arial.ttf", _FONT_SIZE)
        except IOError:
            font = ImageFont.load_default()

        x, y = 0, _TOP_PADDING

        for i, image in enumerate(images):
            # Aspect-ratio-aware resize into frame
            img_ratio = image.width / image.height
            frame_ratio = _FRAME_WIDTH / _FRAME_HEIGHT

            if img_ratio > frame_ratio:
                new_w = _FRAME_WIDTH
                new_h = int(_FRAME_WIDTH / img_ratio)
            else:
                new_h = _FRAME_HEIGHT
                new_w = int(_FRAME_HEIGHT * img_ratio)

            resized = image.resize((new_w, new_h), Image.Resampling.LANCZOS)

            bg_color = resized.getpixel((0, 0))
            frame = Image.new("RGBA", (_FRAME_WIDTH, _FRAME_HEIGHT), bg_color)
            frame.paste(resized, (0, 0))

            # Draw name (right-aligned)
            text = titles[i] if i < len(titles) else "Unknown"
            draw = ImageDraw.Draw(frame)
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            draw.text((_FRAME_WIDTH - 10 - text_w, 10), text, font=font, fill=(0, 0, 0))

            if y + _FRAME_HEIGHT <= grid_h and x + _FRAME_WIDTH <= grid_w:
                merged.paste(frame, (x, y), frame)

            x += _FRAME_WIDTH + _SPACING
            if x >= grid_w:
                x = 0
                y += _FRAME_HEIGHT + _SPACING

        return merged
