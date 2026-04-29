"""Ubisoft game-list grid image renderer.

Generates a grid image of Ubisoft game headers sorted alphabetically
— matching the output of the legacy
``src/games/games/ubisoft/generators/image_generator.py``.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter

from .....shared.paths import default_cache_base_dir

logger = logging.getLogger(__name__)

# Layout constants (based on the legacy generator)
_MIN_CANVAS_WIDTH = 610
_GAME_WIDTH = 150
_GAME_HEIGHT = 110
_GAME_SPACING = 40
_HEADER_HEIGHT = 60
_IMAGE_HEIGHT = 70

_BG_COLOR = (26, 26, 26)
_TEXT_COLOR = (255, 255, 255)
_PLACEHOLDER_COLOR = (51, 51, 51)


class UbisoftImageRenderer:
    """Render a grid of Ubisoft game headers sorted alphabetically."""

    def __init__(self, cache_dir: str | None = None) -> None:
        self._cache_dir = cache_dir or default_cache_base_dir("ubisoft-connect")
        os.makedirs(self._cache_dir, exist_ok=True)
        self._image_cache: dict[str, Image.Image] = {}
        self._session = requests.Session()
        self._session.mount("https://", HTTPAdapter(pool_connections=5, pool_maxsize=10))
        self._session.mount("http://", HTTPAdapter(pool_connections=2, pool_maxsize=5))

    def render(
        self,
        games: dict[str, Any],
        output_path: str,
    ) -> str | None:
        """Build the game grid and save to *output_path*.

        Returns the output path on success, ``None`` on failure.
        """
        if not games:
            logger.warning("No Ubisoft games data — skipping.")
            return None

        sorted_games = sorted(
            (g for g in games.values() if isinstance(g, dict)),
            key=lambda g: str(g.get("title", "")).casefold(),
        )
        if not sorted_games:
            return None

        image = self._generate_grid(sorted_games)
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            image.save(output_path, "PNG", optimize=True)
            logger.info("Ubisoft game grid saved: %s", output_path)
            return output_path
        except Exception as exc:
            logger.error("Failed to save Ubisoft grid: %s", exc)
            return None

    # ── grid assembly ─────────────────────────────────────────────────

    def _generate_grid(self, sorted_games: list[dict[str, Any]]) -> Image.Image:
        cols = self._grid_columns(len(sorted_games))
        rows = math.ceil(len(sorted_games) / cols)
        canvas_w = self._canvas_width(cols)
        canvas_h = _HEADER_HEIGHT + (_GAME_HEIGHT + _GAME_SPACING) * rows + _GAME_SPACING
        canvas = Image.new("RGB", (canvas_w, canvas_h), _BG_COLOR)
        draw = ImageDraw.Draw(canvas)

        self._draw_header(draw, len(sorted_games))

        x_offset = self._grid_x_offset(canvas_w, cols)
        for i, game in enumerate(sorted_games):
            row, col = divmod(i, cols)
            x = x_offset + col * (_GAME_WIDTH + _GAME_SPACING)
            y = _HEADER_HEIGHT + _GAME_SPACING + row * (_GAME_HEIGHT + _GAME_SPACING)
            self._draw_game(canvas, draw, game, x, y)

        return canvas

    def _draw_header(self, draw: ImageDraw.Draw, game_count: int) -> None:
        current_date = datetime.now().strftime("%b %d, %Y")
        header_text = f"Ubisoft Games: {game_count} | {current_date}"
        font = self._get_font("header", 24)
        draw.text((20, 25), header_text, fill=_TEXT_COLOR, font=font)

    def _draw_game(
        self,
        canvas: Image.Image,
        draw: ImageDraw.Draw,
        game: dict[str, Any],
        x: int,
        y: int,
    ) -> None:
        game_id = str(game.get("gameId", ""))
        img_url = game.get("img", "")
        game_img = (
            self._load_game_image(img_url, game_id)
            if img_url
            else self._placeholder()
        )
        if not game_img:
            game_img = self._placeholder()
        canvas.paste(game_img, (x, y))

        title = game.get("title", "Unknown Game")
        font_title = self._get_font("title", 14)
        truncated = self._truncate_text(title, _GAME_WIDTH - 10, font_title)
        draw.text(
            (x + 5, y + _IMAGE_HEIGHT + 8), truncated, fill=_TEXT_COLOR, font=font_title
        )

    # ── image loading ─────────────────────────────────────────────────

    def _load_game_image(self, url: str, game_id: str) -> Image.Image | None:
        cache_key = self._cache_key(game_id, url)
        if cache_key in self._image_cache:
            return self._image_cache[cache_key]

        cached = self._load_from_disk_cache(cache_key)
        if cached:
            resized = cached.resize((_GAME_WIDTH, _IMAGE_HEIGHT), Image.Resampling.LANCZOS)
            self._image_cache[cache_key] = resized
            return resized

        try:
            resp = self._session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            self._save_to_disk_cache(img, cache_key)
            resized = img.resize((_GAME_WIDTH, _IMAGE_HEIGHT), Image.Resampling.LANCZOS)
            self._image_cache[cache_key] = resized
            return resized
        except Exception as exc:
            logger.warning("Ubisoft image download failed (%s): %s", game_id or url, exc)
            return None

    def _load_from_disk_cache(self, cache_key: str) -> Image.Image | None:
        cache_path = Path(self._cache_dir) / f"{cache_key}.jpg"
        if not cache_path.exists():
            return None
        try:
            return Image.open(cache_path).convert("RGB")
        except Exception as exc:
            logger.warning("Corrupt Ubisoft image cache %s: %s", cache_path, exc)
            try:
                cache_path.unlink()
            except OSError as rm_exc:
                logger.warning("Failed to remove corrupt Ubisoft cache %s: %s", cache_path, rm_exc)
            return None

    def _save_to_disk_cache(self, img: Image.Image, cache_key: str) -> None:
        cache_path = Path(self._cache_dir) / f"{cache_key}.jpg"
        try:
            img.save(cache_path, "JPEG", quality=85)
        except Exception as exc:
            logger.warning("Failed to save Ubisoft image cache %s: %s", cache_path, exc)

    @staticmethod
    def _placeholder() -> Image.Image:
        img = Image.new("RGB", (_GAME_WIDTH, _IMAGE_HEIGHT), _PLACEHOLDER_COLOR)
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except IOError:
            font = ImageFont.load_default()
        text = "No Image"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            ((_GAME_WIDTH - tw) // 2, (_IMAGE_HEIGHT - th) // 2),
            text, fill=(102, 102, 102), font=font,
        )
        return img

    @staticmethod
    def _get_font(font_type: str, size: int) -> ImageFont.FreeTypeFont:
        names = ["arial.ttf", "Arial.ttf", "DejaVuSans-Bold.ttf"]
        paths = [
            "/System/Library/Fonts/", "/usr/share/fonts/",
            "C:/Windows/Fonts/", "/usr/share/fonts/truetype/dejavu/",
        ]
        for name in names:
            for p in paths:
                fp = os.path.join(p, name)
                if os.path.exists(fp):
                    try:
                        return ImageFont.truetype(fp, size)
                    except Exception:
                        continue
        return ImageFont.load_default()

    @staticmethod
    def _truncate_text(text: str, max_width: int, font: ImageFont.FreeTypeFont) -> str:
        if not text:
            return ""
        tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        if tmp.textlength(text, font=font) <= max_width:
            return text
        while tmp.textlength(text + "...", font=font) > max_width and len(text) > 0:
            text = text[:-1]
        return text + "..."

    @classmethod
    def _grid_columns(cls, item_count: int) -> int:
        if item_count <= 0:
            return 1

        best_cols = 1
        best_score = float("inf")
        for cols in range(1, item_count + 1):
            rows = math.ceil(item_count / cols)
            width = cls._canvas_width(cols)
            height = cls._canvas_height(rows)
            score = abs(math.log(width / height))
            if score < best_score:
                best_cols = cols
                best_score = score
        return best_cols

    @staticmethod
    def _grid_width(cols: int) -> int:
        return cols * _GAME_WIDTH + max(0, cols - 1) * _GAME_SPACING

    @classmethod
    def _canvas_width(cls, cols: int) -> int:
        return max(_MIN_CANVAS_WIDTH, cls._grid_width(cols) + (_GAME_SPACING * 2))

    @staticmethod
    def _canvas_height(rows: int) -> int:
        return _HEADER_HEIGHT + (_GAME_HEIGHT + _GAME_SPACING) * rows + _GAME_SPACING

    @classmethod
    def _grid_x_offset(cls, canvas_width: int, cols: int) -> int:
        return max(_GAME_SPACING, (canvas_width - cls._grid_width(cols)) // 2)

    @staticmethod
    def _cache_key(game_id: str, url: str) -> str:
        raw = game_id.strip() or hashlib.sha1(url.encode("utf-8")).hexdigest()
        return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in raw)
