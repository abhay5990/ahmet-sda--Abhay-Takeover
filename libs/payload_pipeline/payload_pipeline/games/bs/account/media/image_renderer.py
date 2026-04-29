"""Brawl Stars brawler grid image renderer."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import math
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter

from .....shared.paths import default_cache_base_dir

logger = logging.getLogger(__name__)


_RARITY_PALETTE: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "legendary": ((255, 217, 52), (229, 128, 24)),
    "mythic": ((255, 78, 86), (183, 24, 55)),
    "chromatic": ((255, 107, 214), (93, 80, 255)),
    "epic": ((230, 62, 255), (143, 30, 218)),
    "superrare": ((42, 113, 255), (20, 60, 190)),
    "rare": ((59, 214, 88), (27, 151, 53)),
    "common": ((85, 216, 235), (34, 156, 200)),
}
_FALLBACK_GRAD = ((112, 112, 128), (70, 70, 86))
_RARITY_ORDER = ("legendary", "mythic", "chromatic", "epic", "superrare", "rare", "common")

_CARD_W = 118
_CARD_H = 140
_ICON_MAX_W = 112
_ICON_MAX_H = 100
_LABEL_H = 27
_GAP = 4
_HEADER_H = 70
_HEADER_SUMMARY_FONT_SIZE = 17
_BG_COLOR = (0, 0, 0)

_CDN_URL_TEMPLATE = "https://media.brawltime.ninja/brawlers/{path}/model.webp?size=100"

_FONT_CACHE: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


@dataclass(slots=True)
class _BrawlerCard:
    name: str
    path: str
    rarity: str
    power: int
    rank: int
    trophies: int
    icon: Image.Image


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    for name in ("arial.ttf", "Arial.ttf", "DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(name, size)
            _FONT_CACHE[size] = font
            return font
        except (IOError, OSError):
            continue
    font = ImageFont.load_default()
    _FONT_CACHE[size] = font
    return font


def _bold_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = size + 10_000
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    for name in ("impact.ttf", "Impact.ttf", "ariblk.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(name, size)
            _FONT_CACHE[key] = font
            return font
        except (IOError, OSError):
            continue
    return _font(size)


class BSImageRenderer:
    """Render a readable brawler grid image from resolved Brawl Stars data."""

    def __init__(self, cache_dir: str | None = None) -> None:
        self._cache_dir = Path(cache_dir or default_cache_base_dir("brawl-stars")) / "brawlers"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._session = requests.Session()
        self._session.mount("https://", HTTPAdapter(pool_connections=5, pool_maxsize=10))
        self._session.mount("http://", HTTPAdapter(pool_connections=2, pool_maxsize=5))

    def render(
        self,
        brawlers: dict[str, Any],
        output_path: str,
    ) -> str | None:
        """Build the brawler grid and save it to *output_path*."""
        if not brawlers:
            logger.warning("No brawlers data; skipping image generation.")
            return None

        cards = self._load_cards(brawlers)
        if not cards:
            logger.error("No brawler images could be loaded.")
            return None

        merged = self._create_grid(cards)
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            merged.convert("RGB").save(output_path, format="PNG", optimize=True)
            logger.info("Brawler grid saved: %s", output_path)
            return output_path
        except Exception as exc:
            logger.error("Failed to save brawler grid: %s", exc)
            return None

    def _load_cards(self, brawlers: dict[str, Any]) -> list[_BrawlerCard]:
        iterable = brawlers.values() if isinstance(brawlers, dict) else brawlers

        cards: list[_BrawlerCard] = []
        for brawler in iterable:
            if not isinstance(brawler, dict):
                continue

            name = str(brawler.get("name") or "Unknown").strip()
            path = str(brawler.get("path") or "").strip()
            if not path:
                continue

            rarity = self._normalize_rarity(str(brawler.get("class") or "common"))
            icon = self._get_cached_image(path, _CDN_URL_TEMPLATE.format(path=path))
            if icon is None:
                logger.warning("Could not load brawler image: %s", path)
                continue

            cards.append(
                _BrawlerCard(
                    name=name,
                    path=path,
                    rarity=rarity,
                    power=_to_int(brawler.get("power")),
                    rank=_to_int(brawler.get("rank")),
                    trophies=_to_int(brawler.get("trophies")),
                    icon=icon,
                )
            )

        cards.sort(key=self._sort_key)
        return cards

    def _get_cached_image(self, brawler_path: str, url: str) -> Image.Image | None:
        cache_file = self._cache_dir / f"{brawler_path}.webp"

        if cache_file.exists():
            return self._load_image(cache_file)

        if self._download_to_cache(url, cache_file):
            return self._load_image(cache_file)
        return None

    def _download_to_cache(self, url: str, cache_path: Path) -> bool:
        try:
            resp = self._session.get(url, timeout=10)
            resp.raise_for_status()
            cache_path.write_bytes(resp.content)
            return True
        except Exception as exc:
            logger.warning("Image download failed %s: %s", url, exc)
            return False

    @staticmethod
    def _load_image(path: Path) -> Image.Image | None:
        try:
            return Image.open(path).convert("RGBA")
        except Exception as exc:
            logger.warning("Failed to load cached image %s: %s", path, exc)
            return None

    @classmethod
    def _create_grid(cls, cards: list[_BrawlerCard]) -> Image.Image:
        cols = cls._grid_columns(len(cards))
        rows = -(-len(cards) // cols)

        grid_w = cols * _CARD_W + max(0, cols - 1) * _GAP
        grid_h = _HEADER_H + rows * _CARD_H + max(0, rows - 1) * _GAP

        canvas = Image.new("RGBA", (grid_w, grid_h), (*_BG_COLOR, 255))
        cls._draw_header(canvas, cards)

        for i, brawler in enumerate(cards):
            col, row = i % cols, i // cols
            x = col * (_CARD_W + _GAP)
            y = _HEADER_H + row * (_CARD_H + _GAP)
            card = cls._render_card(brawler)
            canvas.alpha_composite(card, (x, y))

        return canvas

    @staticmethod
    def _render_card(brawler: _BrawlerCard) -> Image.Image:
        card = _vertical_gradient(_CARD_W, _CARD_H, brawler.rarity)

        icon = _prepare_icon(brawler.icon)
        ix = (_CARD_W - icon.width) // 2
        iy = max(4, _CARD_H - _LABEL_H - icon.height + 4)
        card.alpha_composite(icon, (ix, iy))

        _draw_badges(card, brawler)
        _draw_label(card, brawler.name)
        return card

    @staticmethod
    def _draw_header(canvas: Image.Image, cards: list[_BrawlerCard]) -> None:
        draw = ImageDraw.Draw(canvas)
        total = len(cards)
        counts = {
            rarity: sum(1 for card in cards if card.rarity == rarity)
            for rarity in _RARITY_ORDER
        }
        summary_parts = [
            f"{count} {rarity.title()}"
            for rarity, count in counts.items()
            if count and rarity in {"legendary", "mythic", "epic"}
        ]
        summary = "  |  ".join(summary_parts)

        draw.text((8, 8), f"{total} Brawlers", font=_bold_font(30), fill=(255, 255, 255, 255))
        if summary:
            draw.text(
                (10, 43),
                summary,
                font=_bold_font(_HEADER_SUMMARY_FONT_SIZE),
                fill=(232, 232, 240, 255),
            )

    @staticmethod
    def _grid_columns(item_count: int) -> int:
        if item_count <= 0:
            return 1

        best_cols = 1
        best_score = float("inf")
        for cols in range(1, item_count + 1):
            rows = -(-item_count // cols)
            width = cols * _CARD_W + max(0, cols - 1) * _GAP
            height = _HEADER_H + rows * _CARD_H + max(0, rows - 1) * _GAP
            score = abs(math.log(width / height))
            if score < best_score:
                best_cols = cols
                best_score = score
        return best_cols

    @staticmethod
    def _normalize_rarity(value: str) -> str:
        rarity = value.strip().lower().replace(" ", "").replace("_", "")
        return rarity if rarity in _RARITY_PALETTE else "common"

    @staticmethod
    def _sort_key(card: _BrawlerCard) -> tuple[int, int, int, str]:
        try:
            rarity_order = _RARITY_ORDER.index(card.rarity)
        except ValueError:
            rarity_order = len(_RARITY_ORDER)
        return (rarity_order, -card.power, -card.trophies, card.name)


def _prepare_icon(icon: Image.Image) -> Image.Image:
    thumb = icon.copy().convert("RGBA")
    alpha_bbox = thumb.getchannel("A").getbbox()
    if alpha_bbox:
        thumb = thumb.crop(alpha_bbox)
    thumb.thumbnail((_ICON_MAX_W, _ICON_MAX_H), Image.Resampling.LANCZOS)
    return thumb


def _draw_badges(card: Image.Image, brawler: _BrawlerCard) -> None:
    badges: list[tuple[str, tuple[int, int]]] = []
    if brawler.power:
        badges.append((f"P{brawler.power}", (5, 5)))
    if brawler.rank:
        badges.append((f"R{brawler.rank}", (_CARD_W - 38, 5)))

    overlay = Image.new("RGBA", card.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _bold_font(12)
    for text, (x, y) in badges:
        bbox = draw.textbbox((0, 0), text, font=font)
        width = max(30, bbox[2] - bbox[0] + 10)
        draw.rounded_rectangle(
            [(x, y), (x + width, y + 18)],
            radius=4,
            fill=(0, 0, 0, 135),
        )
        draw.text((x + 5, y + 2), text, font=font, fill=(255, 255, 255, 255))
    card.alpha_composite(overlay)


def _draw_label(card: Image.Image, name: str) -> None:
    overlay = Image.new("RGBA", card.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    strip_y = _CARD_H - _LABEL_H
    draw.rectangle([(0, strip_y), (_CARD_W, _CARD_H)], fill=(0, 0, 0, 115))
    card.alpha_composite(overlay)

    draw = ImageDraw.Draw(card)
    text = name.upper()
    max_w = _CARD_W - 8
    chosen = _bold_font(12)
    for size in (15, 14, 13, 12, 11, 10):
        candidate = _bold_font(size)
        bbox = draw.textbbox((0, 0), text, font=candidate)
        if bbox[2] - bbox[0] <= max_w:
            chosen = candidate
            break
        chosen = candidate

    bbox = draw.textbbox((0, 0), text, font=chosen)
    while bbox[2] - bbox[0] > max_w and len(text) > 4:
        text = text[:-3] + ".."
        bbox = draw.textbbox((0, 0), text, font=chosen)

    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (_CARD_W - text_w) // 2
    y = strip_y + (_LABEL_H - text_h) // 2 - 1
    draw.text(
        (x, y),
        text,
        font=chosen,
        fill=(255, 255, 255, 255),
        stroke_width=1,
        stroke_fill=(0, 0, 0, 220),
    )


def _vertical_gradient(w: int, h: int, rarity: str) -> Image.Image:
    top, bottom = _RARITY_PALETTE.get(rarity, _FALLBACK_GRAD)
    strip = Image.new("RGB", (1, 256))
    px = strip.load()
    for y in range(256):
        t = y / 255.0
        px[0, y] = (
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
        )
    return strip.resize((w, h), Image.Resampling.BILINEAR).convert("RGBA")


def _to_int(value: Any) -> int:
    try:
        if value in (None, ""):
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0
