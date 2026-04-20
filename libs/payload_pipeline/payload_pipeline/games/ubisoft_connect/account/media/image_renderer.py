"""Ubisoft game-list grid image renderer.

Generates a grid image of Ubisoft game headers sorted alphabetically
— matching the output of the legacy
``src/games/games/ubisoft/generators/image_generator.py``.
"""

from __future__ import annotations

import logging
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

# Layout constants (match legacy generator)
_CANVAS_WIDTH = 950
_GRID_COLS = 5
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

        # Sort alphabetically by title (matches legacy)
        sorted_games = sorted(
            (g for g in games.values() if isinstance(g, dict)),
            key=lambda g: g.get("title", ""),
        )
        if not sorted_games:
            return None

        image = self._generate_grid(sorted_games)
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            image.save(output_path, "PNG", quality=95)
            logger.info("Ubisoft game grid saved: %s", output_path)
            return output_path
        except Exception as exc:
            logger.error("Failed to save Ubisoft grid: %s", exc)
            return None

    # ── grid assembly ─────────────────────────────────────────────────

    def _generate_grid(self, sorted_games: list[dict[str, Any]]) -> Image.Image:
        rows = (len(sorted_games) + _GRID_COLS - 1) // _GRID_COLS
        canvas_h = _HEADER_HEIGHT + (_GAME_HEIGHT + _GAME_SPACING) * rows + _GAME_SPACING
        canvas = Image.new("RGB", (_CANVAS_WIDTH, canvas_h), _BG_COLOR)
        draw = ImageDraw.Draw(canvas)

        self._draw_header(draw, len(sorted_games))

        for i, game in enumerate(sorted_games):
            row, col = divmod(i, _GRID_COLS)
            x = _GAME_SPACING + col * (_GAME_WIDTH + _GAME_SPACING)
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
        if game_id in self._image_cache:
            return self._image_cache[game_id]

        cache_path = os.path.join(self._cache_dir, f"{game_id}.jpg")
        if os.path.exists(cache_path):
            try:
                img = Image.open(cache_path).convert("RGB")
                resized = img.resize((_GAME_WIDTH, _IMAGE_HEIGHT), Image.Resampling.LANCZOS)
                self._image_cache[game_id] = resized
                return resized
            except Exception:
                try:
                    os.remove(cache_path)
                except Exception:
                    pass

        try:
            resp = self._session.get(url, timeout=10)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            try:
                img.save(cache_path, "JPEG", quality=85)
            except Exception:
                pass
            resized = img.resize((_GAME_WIDTH, _IMAGE_HEIGHT), Image.Resampling.LANCZOS)
            self._image_cache[game_id] = resized
            return resized
        except Exception:
            return None

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
