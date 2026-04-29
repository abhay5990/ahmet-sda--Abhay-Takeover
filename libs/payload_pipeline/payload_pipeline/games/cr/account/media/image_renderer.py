"""Clash Royale card grid image renderer.

Generates a readable, square-like grid image from resolved Clash Royale
card data. Card art is loaded from the StatsRoyale CDN and cached on
disk; if an icon is unavailable, the renderer still produces a polished
placeholder card so media generation does not depend on network access.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from io import BytesIO
import json
import logging
import math
import os
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter

from .....shared.paths import default_cache_base_dir

logger = logging.getLogger(__name__)

_RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
_DEFAULT_SPELLS_PATH = _RESOURCES_DIR / "spells_data.json"

_BASE_URL = "https://cdn.statsroyale.com/v6/cards/full/"

_RARITY_ORDER = ("Champion", "Legendary", "Epic", "Rare", "Common")
_RARITY_RANK = {rarity: index for index, rarity in enumerate(_RARITY_ORDER)}
_RARITY_PALETTE: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "Champion": ((238, 214, 96), (116, 86, 36)),
    "Legendary": ((223, 70, 240), (101, 47, 196)),
    "Epic": ((178, 76, 244), (92, 42, 171)),
    "Rare": ((244, 147, 48), (174, 77, 22)),
    "Common": ((81, 148, 210), (32, 79, 150)),
}
_FALLBACK_GRAD = ((95, 95, 110), (50, 50, 62))

_CARD_W = 116
_CARD_H = 148
_ICON_MAX_W = 108
_ICON_MAX_H = 116
_LABEL_H = 30
_GAP = 4
_HEADER_H = 76
_BG_COLOR = (0, 0, 0)

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


@dataclass(slots=True)
class _CrCard:
    id: str
    name: str
    rarity: str
    normalized_level: int
    level: int
    max_level: int
    evolution_level: int
    max_evolution_level: int
    count: int


class CrImageRenderer:
    """Render a card grid image from resolved Clash Royale data."""

    def __init__(
        self,
        spells_path: str | Path | None = None,
        cache_dir: str | None = None,
        max_workers: int = 8,
    ) -> None:
        self._spells_path = Path(spells_path) if spells_path else _DEFAULT_SPELLS_PATH
        self._cache_dir = Path(
            cache_dir or os.path.join(default_cache_base_dir("clash-royale"), "cards")
        )
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._max_workers = max(1, max_workers)

        self._session = requests.Session()
        self._session.mount("https://", HTTPAdapter(pool_connections=8, pool_maxsize=16))
        self._session.mount("http://", HTTPAdapter(pool_connections=2, pool_maxsize=5))

        self._spells_data: dict[str, dict[str, str]] | None = None

    @property
    def spells_data(self) -> dict[str, dict[str, str]]:
        if self._spells_data is None:
            self._spells_data = self._load_spells()
        return self._spells_data

    def render(
        self,
        cards_data: dict[str, dict[str, Any]],
        output_path: str,
    ) -> str | None:
        """Build card grid and save to *output_path*.

        Returns the path on success, ``None`` on failure.
        """
        if not cards_data:
            logger.warning("No cards data; skipping image generation.")
            return None

        cards = self._prepare_cards(cards_data)
        if not cards:
            return None

        icon_map = self._fetch_all(cards)
        cols = self._grid_columns(len(cards))
        rows = math.ceil(len(cards) / cols)
        grid_w = cols * _CARD_W + max(0, cols - 1) * _GAP
        grid_h = _HEADER_H + rows * _CARD_H + max(0, rows - 1) * _GAP

        canvas = Image.new("RGBA", (grid_w, grid_h), (*_BG_COLOR, 255))
        self._draw_header(canvas, cards)

        for index, card in enumerate(cards):
            col, row = index % cols, index // cols
            x = col * (_CARD_W + _GAP)
            y = _HEADER_H + row * (_CARD_H + _GAP)
            tile = self._render_card(card, icon_map.get(card.id))
            canvas.alpha_composite(tile, (x, y))

        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            canvas.convert("RGB").save(output_path, "PNG", optimize=True)
            logger.info("CR card grid saved: %s", output_path)
            return output_path
        except Exception as exc:
            logger.error("Failed to save card grid: %s", exc)
            return None

    def _load_spells(self) -> dict[str, dict[str, str]]:
        try:
            spells_list = json.loads(self._spells_path.read_text(encoding="utf-8"))
            return {
                str(spell["id"]): {
                    "name": str(spell.get("name") or "Unknown"),
                    "rarity": self._normalize_rarity(str(spell.get("rarity") or "Common")),
                }
                for spell in spells_list
                if isinstance(spell, dict) and "id" in spell
            }
        except Exception as exc:
            logger.error("Failed to load spells data: %s", exc)
            return {}

    def _prepare_cards(self, cards_dict: dict[str, dict[str, Any]]) -> list[_CrCard]:
        cards: list[_CrCard] = []
        for card_id, card_info in cards_dict.items():
            if not isinstance(card_info, dict):
                continue

            spell = self.spells_data.get(str(card_id), {})
            rarity = self._normalize_rarity(str(spell.get("rarity") or "Common"))
            name = str(card_info.get("name") or spell.get("name") or "Unknown").strip()
            cards.append(
                _CrCard(
                    id=str(card_id),
                    name=name,
                    rarity=rarity,
                    normalized_level=_to_int(card_info.get("normalizedLevel"), 1),
                    level=_to_int(card_info.get("level"), 0),
                    max_level=_to_int(card_info.get("maxLevel"), 0),
                    evolution_level=_to_int(card_info.get("evolutionLevel"), 0),
                    max_evolution_level=_to_int(card_info.get("maxEvolutionLevel"), 0),
                    count=_to_int(card_info.get("count"), 0),
                )
            )
        cards.sort(
            key=lambda card: (
                _RARITY_RANK.get(card.rarity, len(_RARITY_ORDER)),
                -card.normalized_level,
                card.name,
            )
        )
        return cards

    def _fetch_all(self, cards: list[_CrCard]) -> dict[str, Image.Image]:
        result: dict[str, Image.Image] = {}
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(self._download_card, card.id): card.id
                for card in cards
            }
            for future in as_completed(futures):
                card_id = futures[future]
                try:
                    icon = future.result()
                    if icon is not None:
                        result[card_id] = icon
                except Exception as exc:
                    logger.debug("CR card image load failed for %s: %s", card_id, exc)
        return result

    def _download_card(self, card_id: str) -> Image.Image | None:
        cache_file = self._cache_dir / f"{card_id}.png"

        if cache_file.exists():
            try:
                return Image.open(cache_file).convert("RGBA")
            except Exception:
                cache_file.unlink(missing_ok=True)

        try:
            response = self._session.get(f"{_BASE_URL}{card_id}.png", timeout=10)
            response.raise_for_status()
            image = Image.open(BytesIO(response.content)).convert("RGBA")
            try:
                image.save(cache_file, "PNG")
            except Exception:
                pass
            return image
        except Exception as exc:
            logger.debug("CR card download failed for %s: %s", card_id, exc)
            return None

    @classmethod
    def _render_card(cls, card: _CrCard, icon: Image.Image | None) -> Image.Image:
        tile = _vertical_gradient(_CARD_W, _CARD_H, card.rarity)
        draw = ImageDraw.Draw(tile)
        border = _RARITY_PALETTE.get(card.rarity, _FALLBACK_GRAD)[0]
        draw.rectangle([(0, 0), (_CARD_W - 1, _CARD_H - 1)], outline=border, width=2)

        if icon is not None:
            thumb = cls._prepare_icon(icon)
            x = (_CARD_W - thumb.width) // 2
            y = max(2, _CARD_H - _LABEL_H - thumb.height + 2)
            tile.alpha_composite(thumb, (x, y))
        else:
            cls._draw_placeholder_icon(tile, card)

        cls._draw_badges(tile, card)
        cls._draw_level_strip(tile, card.normalized_level)
        return tile

    @staticmethod
    def _prepare_icon(icon: Image.Image) -> Image.Image:
        thumb = icon.copy().convert("RGBA")
        alpha_bbox = thumb.getchannel("A").getbbox()
        if alpha_bbox:
            thumb = thumb.crop(alpha_bbox)
        thumb.thumbnail((_ICON_MAX_W, _ICON_MAX_H), Image.Resampling.LANCZOS)
        return thumb

    @staticmethod
    def _draw_placeholder_icon(tile: Image.Image, card: _CrCard) -> None:
        draw = ImageDraw.Draw(tile)
        initials = "".join(part[:1] for part in card.name.split()[:2]).upper() or "CR"
        font = _bold_font(34)
        bbox = draw.textbbox((0, 0), initials, font=font)
        x = (_CARD_W - (bbox[2] - bbox[0])) // 2
        y = 44 - (bbox[3] - bbox[1]) // 2
        draw.text(
            (x, y),
            initials,
            font=font,
            fill=(255, 255, 255, 230),
            stroke_width=2,
            stroke_fill=(0, 0, 0, 180),
        )

    @staticmethod
    def _draw_badges(tile: Image.Image, card: _CrCard) -> None:
        draw = ImageDraw.Draw(tile)
        badge_font = _bold_font(13)

        if card.evolution_level > 0:
            evo_text = f"E{card.evolution_level}"
            bbox = draw.textbbox((0, 0), evo_text, font=badge_font)
            width = max(30, bbox[2] - bbox[0] + 10)
            _draw_pill(
                draw,
                (_CARD_W - width - 5, 5),
                evo_text,
                badge_font,
                (255, 232, 90, 255),
                (85, 45, 150, 190),
                width=width,
            )

    @staticmethod
    def _draw_level_strip(tile: Image.Image, normalized_level: int) -> None:
        overlay = Image.new("RGBA", tile.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        strip_y = _CARD_H - _LABEL_H
        overlay_draw.rectangle([(0, strip_y), (_CARD_W, _CARD_H)], fill=(0, 0, 0, 150))
        tile.alpha_composite(overlay)

        draw = ImageDraw.Draw(tile)
        text = f"Level {normalized_level}"
        max_width = _CARD_W - 8
        font = _bold_font(14)
        for size in (16, 15, 14, 13, 12):
            candidate = _bold_font(size)
            bbox = draw.textbbox((0, 0), text, font=candidate)
            font = candidate
            if bbox[2] - bbox[0] <= max_width:
                break

        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (_CARD_W - text_w) // 2
        y = strip_y + (_LABEL_H - text_h) // 2 - 1
        draw.text(
            (x, y),
            text,
            font=font,
            fill=(255, 222, 76, 255) if normalized_level >= 15 else (255, 255, 255, 255),
            stroke_width=1,
            stroke_fill=(0, 0, 0, 220),
        )

    @staticmethod
    def _draw_header(canvas: Image.Image, cards: list[_CrCard]) -> None:
        draw = ImageDraw.Draw(canvas)
        total = len(cards)
        elite_count = sum(1 for card in cards if card.normalized_level >= 15)
        level_14_count = sum(1 for card in cards if card.normalized_level == 14)
        evolution_count = sum(1 for card in cards if card.evolution_level > 0)
        champions = sum(1 for card in cards if card.rarity == "Champion")
        legendary = sum(1 for card in cards if card.rarity == "Legendary")

        draw.text(
            (8, 8),
            f"{total} Cards",
            font=_bold_font(30),
            fill=(255, 255, 255, 255),
        )
        summary = (
            f"{elite_count} Elite  |  {level_14_count} L14  |  "
            f"{evolution_count} Evolutions  |  {champions} Champion  |  {legendary} Legendary"
        )
        draw.text((10, 45), summary, font=_bold_font(15), fill=(226, 226, 236, 255))
        draw.line([(0, _HEADER_H - 1), (canvas.width, _HEADER_H - 1)], fill=(38, 38, 42), width=1)

    @staticmethod
    def _grid_columns(item_count: int) -> int:
        """Choose the column count whose final canvas is closest to square."""
        if item_count <= 0:
            return 1

        best_cols = 1
        best_score = float("inf")
        for cols in range(1, item_count + 1):
            rows = math.ceil(item_count / cols)
            width = cols * _CARD_W + max(0, cols - 1) * _GAP
            height = _HEADER_H + rows * _CARD_H + max(0, rows - 1) * _GAP
            score = abs(math.log(width / height))
            if score < best_score:
                best_cols = cols
                best_score = score
        return best_cols

    @staticmethod
    def _normalize_rarity(value: str) -> str:
        cleaned = value.strip().lower()
        for rarity in _RARITY_ORDER:
            if cleaned == rarity.lower():
                return rarity
        return "Common"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = ("regular", size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(name, size)
            _FONT_CACHE[key] = font
            return font
        except (IOError, OSError):
            continue
    font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _bold_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = ("bold", size)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    for name in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "impact.ttf"):
        try:
            font = ImageFont.truetype(name, size)
            _FONT_CACHE[key] = font
            return font
        except (IOError, OSError):
            continue
    return _font(size)


def _draw_pill(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    text_fill: tuple[int, int, int, int],
    bg_fill: tuple[int, int, int, int],
    width: int | None = None,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    pill_w = width or max(34, text_w + 10)
    pill_h = 20
    x, y = xy
    draw.rounded_rectangle([(x, y), (x + pill_w, y + pill_h)], radius=4, fill=bg_fill)
    draw.text(
        (x + (pill_w - text_w) // 2, y + (pill_h - text_h) // 2 - 1),
        text,
        font=font,
        fill=text_fill,
    )


def _vertical_gradient(w: int, h: int, rarity: str) -> Image.Image:
    top, bottom = _RARITY_PALETTE.get(rarity, _FALLBACK_GRAD)
    strip = Image.new("RGB", (1, 256))
    pixels = strip.load()
    for y in range(256):
        ratio = y / 255.0
        pixels[0, y] = (
            int(top[0] + (bottom[0] - top[0]) * ratio),
            int(top[1] + (bottom[1] - top[1]) * ratio),
            int(top[2] + (bottom[2] - top[2]) * ratio),
        )
    return strip.resize((w, h), Image.Resampling.BILINEAR).convert("RGBA")


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default
