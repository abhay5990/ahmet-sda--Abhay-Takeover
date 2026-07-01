"""Shared Steam game-list grid renderer.

Generates a grid image of Steam game headers with playtime — used by
both CS2 and Steam media strategies.  Matches the legacy output of
``src/games/games/cs2/generators/image_generator.py`` and
``src/games/games/steam/generators/image_generator.py``.
"""

from __future__ import annotations

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

logger = logging.getLogger(__name__)

# Layout constants (based on the legacy generators)
_CANVAS_WIDTH = 950
_GAME_WIDTH = 150
_GAME_HEIGHT = 110
_GAME_SPACING = 40
_HEADER_HEIGHT = 60
_IMAGE_HEIGHT = 70

_BG_COLOR = (26, 26, 26)
_TEXT_COLOR = (255, 255, 255)
_SUBTITLE_COLOR = (204, 204, 204)
_PLACEHOLDER_COLOR = (51, 51, 51)


class SteamGameGridRenderer:
    """Render a grid of Steam game headers with playtime labels."""

    def __init__(self, cache_dir: str | None = None) -> None:
        self._cache_dir = cache_dir or ""
        self._image_cache: dict[str, Image.Image] = {}
        self._session = requests.Session()
        self._session.mount("https://", HTTPAdapter(pool_connections=5, pool_maxsize=10))
        self._session.mount("http://", HTTPAdapter(pool_connections=2, pool_maxsize=5))

    def render(
        self,
        games: list[dict[str, Any]],
        output_path: str,
        fallback_game: dict[str, Any] | None = None,
    ) -> str | None:
        """Build the game grid and save to *output_path*.

        *fallback_game* is used when ``games`` is empty (e.g. CS2 shows a
        single CS2 entry with hours_played).

        Returns the output path on success, ``None`` on failure.
        """
        if not games and fallback_game:
            games = [fallback_game]
        if not games:
            logger.warning("No games data — skipping image generation.")
            return None

        if self._cache_dir:
            os.makedirs(self._cache_dir, exist_ok=True)

        # Sort by playtime descending (matches legacy)
        sorted_games = sorted(
            games, key=lambda g: g.get("playtime_forever", 0), reverse=True
        )

        image = self._generate_grid(sorted_games)
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            image.save(output_path, "PNG", quality=95)
            logger.info("Game grid saved: %s", output_path)
            return output_path
        except Exception as exc:
            logger.error("Failed to save game grid: %s", exc)
            return None

    # ── grid assembly ─────────────────────────────────────────────────

    def _generate_grid(self, sorted_games: list[dict[str, Any]]) -> Image.Image:
        cols = self._grid_columns(len(sorted_games))
        rows = math.ceil(len(sorted_games) / cols)
        canvas_width = self._canvas_width(cols)
        canvas_height = (
            _HEADER_HEIGHT
            + (_GAME_HEIGHT + _GAME_SPACING) * rows
            + _GAME_SPACING
        )
        canvas = Image.new("RGB", (canvas_width, canvas_height), _BG_COLOR)
        draw = ImageDraw.Draw(canvas)

        self._draw_header(draw, len(sorted_games))

        x_offset = self._grid_x_offset(canvas_width, cols)
        for i, game in enumerate(sorted_games):
            row, col = divmod(i, cols)
            x = x_offset + col * (_GAME_WIDTH + _GAME_SPACING)
            y = _HEADER_HEIGHT + _GAME_SPACING + row * (_GAME_HEIGHT + _GAME_SPACING)
            try:
                self._draw_game(canvas, draw, game, x, y)
            except Exception as exc:
                # One malformed game must not sink the whole grid (which would
                # leave the offer with no image → marketplace 400).
                logger.warning(
                    "Skipping game tile (appid=%s): %s",
                    game.get("appid"), exc,
                )

        return canvas

    def _draw_header(self, draw: ImageDraw.Draw, game_count: int) -> None:
        current_date = datetime.now().strftime("%b %d, %Y at %I:%M %p")
        header_text = f"Games: {game_count} | {current_date}"
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
        app_id = str(game.get("appid", ""))
        img_url = game.get("img", "")
        game_img = (
            self._load_game_image(img_url, app_id)
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

        playtime = game.get("playtime_forever", 0)
        font_hours = self._get_font("subtitle", 12)
        draw.text(
            (x + 5, y + _IMAGE_HEIGHT + 30),
            f"{round(playtime, 1)} h.",
            fill=_SUBTITLE_COLOR,
            font=font_hours,
        )

    # ── image loading ─────────────────────────────────────────────────

    def _load_game_image(self, url: str, app_id: str) -> Image.Image | None:
        if app_id in self._image_cache:
            return self._image_cache[app_id]

        cached = self._load_from_disk_cache(app_id)
        if cached:
            resized = cached.resize((_GAME_WIDTH, _IMAGE_HEIGHT), Image.Resampling.LANCZOS)
            self._image_cache[app_id] = resized
            return resized

        try:
            resp = self._session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGB")
            self._save_to_disk_cache(img, app_id)
            resized = img.resize((_GAME_WIDTH, _IMAGE_HEIGHT), Image.Resampling.LANCZOS)
            self._image_cache[app_id] = resized
            return resized
        except Exception as exc:
            logger.warning("Image download failed (%s): %s", app_id, exc)
            return None

    def _load_from_disk_cache(self, app_id: str) -> Image.Image | None:
        if not self._cache_dir:
            return None
        cache_path = os.path.join(self._cache_dir, f"{app_id}.jpg")
        if not os.path.exists(cache_path):
            return None
        try:
            return Image.open(cache_path).convert("RGB")
        except Exception as exc:
            logger.warning("Corrupt disk cache for app %s, removing: %s", app_id, exc)
            try:
                os.remove(cache_path)
            except OSError as rm_exc:
                logger.warning("Failed to remove corrupt cache %s: %s", cache_path, rm_exc)
            return None

    def _save_to_disk_cache(self, img: Image.Image, app_id: str) -> None:
        if not self._cache_dir:
            return
        cache_path = os.path.join(self._cache_dir, f"{app_id}.jpg")
        try:
            img.save(cache_path, "JPEG", quality=85)
        except Exception as exc:
            logger.warning("Failed to save disk cache for app %s: %s", app_id, exc)

    # ── helpers ────────────────────────────────────────────────────────

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
            text,
            fill=(102, 102, 102),
            font=font,
        )
        return img

    @staticmethod
    def _get_font(font_type: str, size: int) -> ImageFont.FreeTypeFont:
        font_names = {
            "title": ["arial.ttf", "Arial.ttf", "DejaVuSans-Bold.ttf"],
            "subtitle": ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"],
            "header": ["arial.ttf", "Arial.ttf", "DejaVuSans-Bold.ttf"],
        }
        common_paths = [
            "/System/Library/Fonts/",
            "/usr/share/fonts/",
            "C:/Windows/Fonts/",
            "/usr/share/fonts/truetype/dejavu/",
        ]
        for name in font_names.get(font_type, ["arial.ttf"]):
            for path in common_paths:
                full_path = os.path.join(path, name)
                if os.path.exists(full_path):
                    try:
                        return ImageFont.truetype(full_path, size)
                    except Exception as exc:
                        logger.debug("Font load failed %s: %s", full_path, exc)
                        continue
        return ImageFont.load_default()

    @staticmethod
    def _truncate_text(
        text: str, max_width: int, font: ImageFont.FreeTypeFont
    ) -> str:
        if not text:
            return ""
        # Collapse newlines/extra whitespace: Pillow's textlength() raises
        # "can't measure length of multiline text" on any string containing a
        # newline (some LZT titles arrive with a trailing "\r\n", e.g.
        # "Resident Evil Village\r\n").
        text = " ".join(text.split())
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
        """Choose a column count that keeps large Steam grids readable."""
        if item_count <= 0:
            return 1

        best_cols = 1
        best_score = float("inf")
        for cols in range(1, item_count + 1):
            rows = math.ceil(item_count / cols)
            width = cls._ideal_canvas_width(cols)
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
    def _ideal_canvas_width(cls, cols: int) -> int:
        return cls._grid_width(cols) + (_GAME_SPACING * 2)

    @classmethod
    def _canvas_width(cls, cols: int) -> int:
        return max(_CANVAS_WIDTH, cls._ideal_canvas_width(cols))

    @staticmethod
    def _canvas_height(rows: int) -> int:
        return _HEADER_HEIGHT + (_GAME_HEIGHT + _GAME_SPACING) * rows + _GAME_SPACING

    @classmethod
    def _grid_x_offset(cls, canvas_width: int, cols: int) -> int:
        return max(_GAME_SPACING, (canvas_width - cls._grid_width(cols)) // 2)
