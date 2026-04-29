"""League of Legends champion and skin grid image renderer."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from io import BytesIO
import json
import logging
import math
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter

from .....shared.paths import default_cache_base_dir

logger = logging.getLogger(__name__)

_RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
_DEFAULT_DATA_PATH = _RESOURCES_DIR / "LolAllData.json"

_GAP = 5
_HEADER_H = 58
_TOP_PADDING = 10
_BOTTOM_PADDING = 8
_CARD_RADIUS = 7

_BG_TOP = (9, 13, 25)
_BG_BOTTOM = (15, 20, 37)
_CARD_BACKGROUND = (20, 27, 45, 255)
_CARD_BORDER = (103, 83, 48, 255)
_CARD_HIGHLIGHT = (200, 158, 75, 255)
_LABEL_BACKGROUND = (0, 0, 0, 155)
_TEXT_COLOR = (246, 242, 232, 255)
_MUTED_TEXT_COLOR = (180, 188, 204, 255)
_PLACEHOLDER_FILL = (32, 39, 58, 255)
_PLACEHOLDER_BORDER = (92, 104, 132, 255)

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


@dataclass(frozen=True, slots=True)
class _LolGridConfig:
    data_key: str
    cache_subdir: str
    file_prefix: str
    heading: str
    card_width: int
    card_height: int
    image_box: tuple[int, int]
    image_top: int
    label_height: int
    title_font_size: int
    max_columns: int
    image_mode: str


@dataclass(frozen=True, slots=True)
class _LolAsset:
    id: str
    title: str
    src: str


@dataclass(slots=True)
class _LolCard:
    asset: _LolAsset
    image: Image.Image | None


_CHAMPION_GRID = _LolGridConfig(
    data_key="Champions",
    cache_subdir="champions",
    file_prefix="Champions",
    heading="Champions",
    card_width=118,
    card_height=148,
    image_box=(100, 100),
    image_top=10,
    label_height=32,
    title_font_size=14,
    max_columns=12,
    image_mode="contain",
)
_SKIN_GRID = _LolGridConfig(
    data_key="Skins",
    cache_subdir="skins",
    file_prefix="Skins",
    heading="Skins",
    card_width=320,
    card_height=190,
    image_box=(306, 146),
    image_top=7,
    label_height=36,
    title_font_size=15,
    max_columns=8,
    image_mode="cover",
)


class LolImageRenderer:
    """Render readable champion and skin grids from resolved LoL inventory data."""

    def __init__(
        self,
        data_path: str | Path | None = None,
        cache_dir: str | Path | None = None,
        max_workers: int = 8,
    ) -> None:
        self._data_path = Path(data_path) if data_path else _DEFAULT_DATA_PATH
        self._cache_dir = Path(
            cache_dir or (Path(default_cache_base_dir("league-of-legends")) / "images")
        )
        (self._cache_dir / "champions").mkdir(parents=True, exist_ok=True)
        (self._cache_dir / "skins").mkdir(parents=True, exist_ok=True)
        self._max_workers = max(1, max_workers)

        self._session = requests.Session()
        self._session.mount("https://", HTTPAdapter(pool_connections=8, pool_maxsize=16))
        self._session.mount("http://", HTTPAdapter(pool_connections=2, pool_maxsize=5))

        self._lol_data: dict[str, Any] | None = None
        self._asset_maps: dict[str, dict[str, _LolAsset]] | None = None

    @property
    def lol_data(self) -> dict[str, Any]:
        if self._lol_data is None:
            self._lol_data = self._load_data()
        return self._lol_data

    def render(
        self,
        champion_ids: list[int],
        skin_ids: list[int],
        output_dir: str,
        item_id: str = "unknown",
    ) -> list[str]:
        """Build champion and skin grids, returning saved file paths."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        saved: list[str] = []
        for config, ids in (
            (_CHAMPION_GRID, champion_ids),
            (_SKIN_GRID, skin_ids),
        ):
            if not ids:
                continue

            image = self._render_grid_for_type(ids, config)
            if image is None:
                continue

            file_name = f"{config.file_prefix}.{_sanitize_filename(item_id)}.png"
            save_path = output_path / file_name
            try:
                image.convert("RGB").save(save_path, "PNG", optimize=True)
                logger.info("LoL %s grid saved: %s", config.heading, save_path)
                saved.append(str(save_path))
            except Exception as exc:
                logger.error("Failed to save LoL %s grid: %s", config.heading, exc)

        return saved

    def _render_grid_for_type(
        self,
        ids: list[int],
        config: _LolGridConfig,
    ) -> Image.Image | None:
        assets = self._resolve_assets(ids, config)
        if not assets:
            logger.warning("No LoL %s assets found for rendering.", config.heading)
            return None

        image_map = self._fetch_all(assets, config)
        cards = [_LolCard(asset=asset, image=image_map.get(asset.id)) for asset in assets]
        return self._render_grid(cards, config)

    def _load_data(self) -> dict[str, Any]:
        try:
            return json.loads(self._data_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to load LoL data from %s: %s", self._data_path, exc)
            return {"Champions": [], "Skins": []}

    def _asset_map(self, data_key: str) -> dict[str, _LolAsset]:
        if self._asset_maps is None:
            self._asset_maps = {
                "Champions": self._parse_assets(self.lol_data.get("Champions", [])),
                "Skins": self._parse_assets(self.lol_data.get("Skins", [])),
            }
        return self._asset_maps.get(data_key, {})

    @staticmethod
    def _parse_assets(raw_entries: object) -> dict[str, _LolAsset]:
        if not isinstance(raw_entries, list):
            return {}

        assets: dict[str, _LolAsset] = {}
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue

            asset_id = str(entry.get("id") or "").strip()
            title = str(entry.get("title") or "").strip()
            src = str(entry.get("src") or "").strip()
            if not asset_id or not title or not src:
                continue

            assets[asset_id] = _LolAsset(id=asset_id, title=title, src=src)
        return assets

    def _resolve_assets(
        self,
        ids: list[int],
        config: _LolGridConfig,
    ) -> list[_LolAsset]:
        assets_by_id = self._asset_map(config.data_key)
        seen: set[str] = set()
        assets: list[_LolAsset] = []

        for raw_id in ids:
            asset_id = str(raw_id)
            if asset_id in seen:
                continue
            seen.add(asset_id)

            asset = assets_by_id.get(asset_id)
            if asset is None:
                logger.debug("Unknown LoL %s id: %s", config.heading, asset_id)
                continue
            if config.data_key == "Skins" and asset.title.strip().lower() == "default":
                continue
            assets.append(asset)

        assets.sort(key=lambda asset: asset.title.casefold())
        return assets

    def _fetch_all(
        self,
        assets: list[_LolAsset],
        config: _LolGridConfig,
    ) -> dict[str, Image.Image]:
        if not assets:
            return {}

        result: dict[str, Image.Image] = {}
        worker_count = min(self._max_workers, len(assets))
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {
                pool.submit(self._load_or_download_cached, asset, config): asset.id
                for asset in assets
            }
            for future in as_completed(futures):
                asset_id = futures[future]
                try:
                    image = future.result()
                    if image is not None:
                        result[asset_id] = image
                except Exception as exc:
                    logger.debug("LoL image load failed for %s: %s", asset_id, exc)
        return result

    def _load_or_download_cached(
        self,
        asset: _LolAsset,
        config: _LolGridConfig,
    ) -> Image.Image | None:
        cache_path = self._cache_dir / config.cache_subdir / f"{asset.id}.png"

        if cache_path.exists():
            image = self._load_cached_image(cache_path)
            if image is not None:
                return image
            cache_path.unlink(missing_ok=True)

        image = self._download_image(asset.src)
        if image is None:
            return None

        try:
            image.save(cache_path, "PNG")
        except Exception as exc:
            logger.debug("Failed to cache LoL image %s: %s", cache_path, exc)
        return image

    @staticmethod
    def _load_cached_image(path: Path) -> Image.Image | None:
        try:
            image = Image.open(path).convert("RGBA")
            image.load()
            return image
        except Exception as exc:
            logger.debug("Failed to load cached LoL image %s: %s", path, exc)
            return None

    def _download_image(self, url: str) -> Image.Image | None:
        try:
            response = self._session.get(url, timeout=(8, 20))
            response.raise_for_status()
            image = Image.open(BytesIO(response.content)).convert("RGBA")
            image.load()
            return image
        except Exception as exc:
            logger.warning("LoL image download failed %s: %s", url, exc)
            return None

    @classmethod
    def _render_grid(
        cls,
        cards: list[_LolCard],
        config: _LolGridConfig,
    ) -> Image.Image:
        columns = cls._grid_columns(len(cards), config)
        rows = math.ceil(len(cards) / columns)
        canvas_w = columns * config.card_width + max(0, columns - 1) * _GAP
        canvas_h = (
            _HEADER_H
            + _TOP_PADDING
            + rows * config.card_height
            + max(0, rows - 1) * _GAP
            + _BOTTOM_PADDING
        )

        canvas = _canvas_gradient(canvas_w, canvas_h)
        cls._draw_header(canvas, config=config, count=len(cards))

        for index, card_data in enumerate(cards):
            col, row = index % columns, index // columns
            x = col * (config.card_width + _GAP)
            y = _HEADER_H + _TOP_PADDING + row * (config.card_height + _GAP)
            card = cls._render_card(card_data, config)
            canvas.alpha_composite(card, (x, y))

        return canvas

    @staticmethod
    def _grid_columns(item_count: int, config: _LolGridConfig) -> int:
        if item_count <= 0:
            return 1

        best_columns = 1
        best_score = float("inf")
        for columns in range(1, min(item_count, config.max_columns) + 1):
            rows = math.ceil(item_count / columns)
            width = columns * config.card_width + max(0, columns - 1) * _GAP
            height = (
                _HEADER_H
                + _TOP_PADDING
                + rows * config.card_height
                + max(0, rows - 1) * _GAP
                + _BOTTOM_PADDING
            )
            score = abs(math.log(width / height))
            if score < best_score:
                best_columns = columns
                best_score = score
        return best_columns

    @classmethod
    def _render_card(cls, card_data: _LolCard, config: _LolGridConfig) -> Image.Image:
        card = Image.new("RGBA", (config.card_width, config.card_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(card)
        draw.rounded_rectangle(
            [(0, 0), (config.card_width - 1, config.card_height - 1)],
            radius=_CARD_RADIUS,
            fill=_CARD_BACKGROUND,
            outline=_CARD_BORDER,
            width=1,
        )
        draw.line(
            [(_CARD_RADIUS, 1), (config.card_width - _CARD_RADIUS, 1)],
            fill=_CARD_HIGHLIGHT,
            width=1,
        )

        if card_data.image is None:
            cls._draw_placeholder(card, card_data.asset.title, config)
        elif config.image_mode == "cover":
            image = _cover_image(card_data.image, config.image_box)
            image_x = (config.card_width - image.width) // 2
            card.alpha_composite(image, (image_x, config.image_top))
        else:
            image = _contain_image(card_data.image, config.image_box)
            image_x = (config.card_width - image.width) // 2
            image_y = config.image_top + (config.image_box[1] - image.height) // 2
            card.alpha_composite(image, (image_x, image_y))

        cls._draw_title(card, card_data.asset.title, config)
        return card

    @staticmethod
    def _draw_header(
        canvas: Image.Image,
        *,
        config: _LolGridConfig,
        count: int,
    ) -> None:
        draw = ImageDraw.Draw(canvas)
        heading = (
            config.heading[:-1]
            if count == 1 and config.heading.endswith("s")
            else config.heading
        )
        title = f"{count} {heading}"

        _draw_fitted_text(
            draw,
            title,
            (14, 9, canvas.width - 14, 47),
            font_size=30,
            bold=True,
            fill=_TEXT_COLOR,
            align="left",
            min_size=18,
        )
        draw.line(
            [(0, _HEADER_H - 1), (canvas.width, _HEADER_H - 1)],
            fill=(255, 255, 255, 34),
            width=1,
        )

    @staticmethod
    def _draw_title(card: Image.Image, title: str, config: _LolGridConfig) -> None:
        overlay = Image.new("RGBA", card.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        label_y = config.card_height - config.label_height
        overlay_draw.rounded_rectangle(
            [(4, label_y + 2), (config.card_width - 4, config.card_height - 5)],
            radius=5,
            fill=_LABEL_BACKGROUND,
        )
        card.alpha_composite(overlay)

        text = title.upper() if config.data_key == "Champions" else title
        draw = ImageDraw.Draw(card)
        _draw_fitted_text(
            draw,
            text,
            (8, label_y, config.card_width - 8, config.card_height - 4),
            font_size=config.title_font_size,
            bold=True,
            fill=_TEXT_COLOR,
            align="center",
            min_size=8,
            stroke_width=1,
            stroke_fill=(0, 0, 0, 190),
        )

    @staticmethod
    def _draw_placeholder(
        card: Image.Image,
        title: str,
        config: _LolGridConfig,
    ) -> None:
        draw = ImageDraw.Draw(card)
        box_w, box_h = config.image_box
        x1 = (config.card_width - box_w) // 2
        y1 = config.image_top
        x2 = x1 + box_w
        y2 = y1 + box_h
        draw.rounded_rectangle(
            [(x1, y1), (x2, y2)],
            radius=5,
            fill=_PLACEHOLDER_FILL,
            outline=_PLACEHOLDER_BORDER,
            width=1,
        )

        initials = "".join(part[:1] for part in title.split()[:2]).upper() or "LOL"
        _draw_fitted_text(
            draw,
            initials,
            (x1, y1, x2, y2),
            font_size=max(20, min(42, box_h // 2)),
            bold=True,
            fill=_MUTED_TEXT_COLOR,
            align="center",
            min_size=14,
        )


def _font(
    size: int,
    *,
    bold: bool = False,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = ("bold" if bold else "regular", size)
    cached = _FONT_CACHE.get(key)
    if cached is not None:
        return cached

    if bold:
        candidates = (
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "arialbd.ttf",
            "Arial Bold.ttf",
            "DejaVuSans-Bold.ttf",
            "impact.ttf",
        )
    else:
        candidates = (
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "arial.ttf",
            "Arial.ttf",
            "DejaVuSans.ttf",
        )

    for candidate in candidates:
        try:
            font = ImageFont.truetype(candidate, size)
            _FONT_CACHE[key] = font
            return font
        except (OSError, IOError):
            continue

    font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _draw_fitted_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    area: tuple[int, int, int, int],
    *,
    font_size: int,
    bold: bool,
    fill: tuple[int, int, int, int],
    align: str,
    min_size: int,
    stroke_width: int = 0,
    stroke_fill: tuple[int, int, int, int] | None = None,
) -> None:
    x1, y1, x2, y2 = area
    max_width = max(1, x2 - x1)
    current_text = str(text or "").strip()
    current_size = font_size
    chosen_font = _font(current_size, bold=bold)
    bbox = draw.textbbox(
        (0, 0),
        current_text,
        font=chosen_font,
        stroke_width=stroke_width,
    )

    while current_size > min_size and (bbox[2] - bbox[0]) > max_width:
        current_size -= 1
        chosen_font = _font(current_size, bold=bold)
        bbox = draw.textbbox(
            (0, 0),
            current_text,
            font=chosen_font,
            stroke_width=stroke_width,
        )

    while (bbox[2] - bbox[0]) > max_width and len(current_text) > 4:
        current_text = current_text[:-4].rstrip() + "..."
        bbox = draw.textbbox(
            (0, 0),
            current_text,
            font=chosen_font,
            stroke_width=stroke_width,
        )

    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    if align == "left":
        text_x = x1 - bbox[0]
    else:
        text_x = x1 + (max_width - text_width) // 2 - bbox[0]
    text_y = y1 + ((y2 - y1) - text_height) // 2 - bbox[1] - 1
    draw.text(
        (text_x, text_y),
        current_text,
        font=chosen_font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )


def _contain_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    prepared = image.copy().convert("RGBA")
    alpha_bbox = prepared.getchannel("A").getbbox()
    if alpha_bbox:
        prepared = prepared.crop(alpha_bbox)
    prepared.thumbnail(size, Image.Resampling.LANCZOS)
    return prepared


def _cover_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    prepared = image.copy().convert("RGBA")
    source_ratio = prepared.width / prepared.height
    target_ratio = target_w / target_h

    if source_ratio > target_ratio:
        new_w = int(prepared.height * target_ratio)
        left = (prepared.width - new_w) // 2
        prepared = prepared.crop((left, 0, left + new_w, prepared.height))
    else:
        new_h = int(prepared.width / target_ratio)
        top = max(0, (prepared.height - new_h) // 3)
        prepared = prepared.crop((0, top, prepared.width, top + new_h))

    return prepared.resize(size, Image.Resampling.LANCZOS)


def _canvas_gradient(width: int, height: int) -> Image.Image:
    strip = Image.new("RGB", (1, 256))
    pixels = strip.load()
    for y in range(256):
        ratio = y / 255.0
        pixels[0, y] = (
            int(_BG_TOP[0] + (_BG_BOTTOM[0] - _BG_TOP[0]) * ratio),
            int(_BG_TOP[1] + (_BG_BOTTOM[1] - _BG_TOP[1]) * ratio),
            int(_BG_TOP[2] + (_BG_BOTTOM[2] - _BG_TOP[2]) * ratio),
        )
    return strip.resize((width, height), Image.Resampling.BILINEAR).convert("RGBA")


def _sanitize_filename(value: str) -> str:
    cleaned = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_"
        for char in str(value or "").strip()
    )
    return cleaned.strip("._")[:120] or "unknown"
