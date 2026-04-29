"""Valorant inventory grid image renderer."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from io import BytesIO
import json
import logging
import math
from pathlib import Path
import re
import unicodedata

import requests
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter

from .....shared.paths import default_cache_base_dir

logger = logging.getLogger(__name__)

_RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"

_GAP = 5
_HEADER_H = 58
_TOP_PADDING = 10
_BOTTOM_PADDING = 8
_CARD_RADIUS = 7

_BG_TOP = (10, 16, 23)
_BG_BOTTOM = (18, 22, 31)
_CARD_BACKGROUND = (23, 29, 38, 255)
_CARD_BORDER = (92, 101, 112, 255)
_CARD_HIGHLIGHT = (255, 70, 85, 255)
_LABEL_BACKGROUND = (0, 0, 0, 150)
_TEXT_COLOR = (246, 248, 247, 255)
_MUTED_TEXT_COLOR = (178, 188, 194, 255)
_PLACEHOLDER_FILL = (34, 41, 51, 255)
_PLACEHOLDER_BORDER = (93, 107, 122, 255)

_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


@dataclass(frozen=True, slots=True)
class _ValorantGridConfig:
    key: str
    resource_file: str
    cache_subdir: str
    file_slug: str
    heading: str
    card_width: int
    card_height: int
    image_box: tuple[int, int]
    image_top: int
    label_height: int
    title_font_size: int
    max_columns: int


@dataclass(frozen=True, slots=True)
class _ValorantAsset:
    id: str
    title: str
    src: str


@dataclass(slots=True)
class _ValorantCard:
    asset: _ValorantAsset
    image: Image.Image | None


_SKIN_GRID = _ValorantGridConfig(
    key="skins",
    resource_file="dataSkins.json",
    cache_subdir="skins",
    file_slug="weapons",
    heading="Weapon Skins",
    card_width=174,
    card_height=116,
    image_box=(164, 72),
    image_top=8,
    label_height=28,
    title_font_size=12,
    max_columns=14,
)
_AGENT_GRID = _ValorantGridConfig(
    key="agents",
    resource_file="dataAgents.json",
    cache_subdir="agents",
    file_slug="agents",
    heading="Agents",
    card_width=118,
    card_height=150,
    image_box=(104, 104),
    image_top=8,
    label_height=30,
    title_font_size=14,
    max_columns=12,
)
_BUDDY_GRID = _ValorantGridConfig(
    key="buddies",
    resource_file="dataBuddies.json",
    cache_subdir="buddies",
    file_slug="buddies",
    heading="Buddies",
    card_width=132,
    card_height=148,
    image_box=(108, 96),
    image_top=8,
    label_height=34,
    title_font_size=12,
    max_columns=12,
)


class ValorantImageRenderer:
    """Render Valorant weapon skin, agent, and buddy inventory grids."""

    def __init__(
        self,
        resources_dir: str | Path | None = None,
        cache_dir: str | Path | None = None,
        max_workers: int = 10,
    ) -> None:
        self._resources_dir = Path(resources_dir) if resources_dir else _RESOURCES_DIR
        self._cache_dir = Path(
            cache_dir or (Path(default_cache_base_dir("valorant")) / "icons")
        )
        for subdir in ("skins", "agents", "buddies"):
            (self._cache_dir / subdir).mkdir(parents=True, exist_ok=True)

        self._max_workers = max(1, max_workers)
        self._session = requests.Session()
        self._session.mount("https://", HTTPAdapter(pool_connections=10, pool_maxsize=20))
        self._session.mount("http://", HTTPAdapter(pool_connections=2, pool_maxsize=5))
        self._asset_maps: dict[str, dict[str, _ValorantAsset]] = {}

    def render(
        self,
        *,
        skin_names: list[str],
        agent_names: list[str],
        buddy_names: list[str],
        output_dir: str,
        item_id: str = "unknown",
    ) -> list[str]:
        """Build all available Valorant inventory grids and return saved paths."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        saved: list[str] = []
        for config, names in (
            (_SKIN_GRID, skin_names),
            (_AGENT_GRID, agent_names),
            (_BUDDY_GRID, buddy_names),
        ):
            if not names:
                continue

            image = self._render_grid_for_type(names, config)
            if image is None:
                continue

            save_path = output_path / (
                f"valorant_{config.file_slug}.{_sanitize_filename(item_id)}.png"
            )
            try:
                image.convert("RGB").save(save_path, "PNG", optimize=True)
                logger.info("Valorant %s grid saved: %s", config.heading, save_path)
                saved.append(str(save_path))
            except Exception as exc:
                logger.error("Failed to save Valorant %s grid: %s", config.heading, exc)

        return saved

    def _render_grid_for_type(
        self,
        names: list[str],
        config: _ValorantGridConfig,
    ) -> Image.Image | None:
        assets = self._resolve_assets(names, config)
        if not assets:
            logger.warning("No Valorant %s assets found for rendering.", config.heading)
            return None

        image_map = self._fetch_all(assets, config)
        cards = [_ValorantCard(asset=asset, image=image_map.get(asset.id)) for asset in assets]
        return self._render_grid(cards, config)

    def _resolve_assets(
        self,
        names: list[str],
        config: _ValorantGridConfig,
    ) -> list[_ValorantAsset]:
        assets_by_name = self._asset_map(config)
        seen: set[str] = set()
        assets: list[_ValorantAsset] = []

        for name in names:
            normalized = _normalize_name(name)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)

            asset = assets_by_name.get(normalized)
            if asset is None:
                logger.debug("Unknown Valorant %s name: %s", config.heading, name)
                continue
            assets.append(asset)

        return assets

    def _asset_map(self, config: _ValorantGridConfig) -> dict[str, _ValorantAsset]:
        cached = self._asset_maps.get(config.key)
        if cached is not None:
            return cached

        path = self._resources_dir / config.resource_file
        assets: dict[str, _ValorantAsset] = {}
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to load Valorant resource %s: %s", path, exc)
            rows = []

        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                asset_id = str(row.get("data_id") or "").strip()
                title = str(row.get("alt") or "").strip()
                src = str(row.get("src") or "").strip()
                if not asset_id or not title or not src:
                    continue
                normalized = _normalize_name(title)
                if normalized and normalized not in assets:
                    assets[normalized] = _ValorantAsset(
                        id=asset_id,
                        title=title,
                        src=src,
                    )

        self._asset_maps[config.key] = assets
        return assets

    def _fetch_all(
        self,
        assets: list[_ValorantAsset],
        config: _ValorantGridConfig,
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
                    logger.debug("Valorant image load failed for %s: %s", asset_id, exc)
        return result

    def _load_or_download_cached(
        self,
        asset: _ValorantAsset,
        config: _ValorantGridConfig,
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
            logger.debug("Failed to cache Valorant image %s: %s", cache_path, exc)
        return image

    @staticmethod
    def _load_cached_image(path: Path) -> Image.Image | None:
        try:
            image = Image.open(path).convert("RGBA")
            image.load()
            return image
        except Exception as exc:
            logger.debug("Failed to load cached Valorant image %s: %s", path, exc)
            return None

    def _download_image(self, url: str) -> Image.Image | None:
        try:
            response = self._session.get(url, timeout=(8, 20))
            response.raise_for_status()
            image = Image.open(BytesIO(response.content)).convert("RGBA")
            image.load()
            return image
        except Exception as exc:
            logger.warning("Valorant image download failed %s: %s", url, exc)
            return None

    @classmethod
    def _render_grid(
        cls,
        cards: list[_ValorantCard],
        config: _ValorantGridConfig,
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
    def _grid_columns(item_count: int, config: _ValorantGridConfig) -> int:
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
    def _render_card(
        cls,
        card_data: _ValorantCard,
        config: _ValorantGridConfig,
    ) -> Image.Image:
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
        config: _ValorantGridConfig,
        count: int,
    ) -> None:
        draw = ImageDraw.Draw(canvas)
        heading = (
            config.heading[:-1]
            if count == 1 and config.heading.endswith("s")
            else config.heading
        )
        _draw_fitted_text(
            draw,
            f"{count} {heading}",
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
    def _draw_title(card: Image.Image, title: str, config: _ValorantGridConfig) -> None:
        overlay = Image.new("RGBA", card.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        label_y = config.card_height - config.label_height
        overlay_draw.rounded_rectangle(
            [(4, label_y + 2), (config.card_width - 4, config.card_height - 5)],
            radius=5,
            fill=_LABEL_BACKGROUND,
        )
        card.alpha_composite(overlay)

        _draw_fitted_text(
            ImageDraw.Draw(card),
            title,
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
        config: _ValorantGridConfig,
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

        initials = "".join(part[:1] for part in title.split()[:2]).upper() or "VAL"
        _draw_fitted_text(
            draw,
            initials,
            (x1, y1, x2, y2),
            font_size=max(18, min(38, box_h // 2)),
            bold=True,
            fill=_MUTED_TEXT_COLOR,
            align="center",
            min_size=12,
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

    candidates = (
        (
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "arialbd.ttf",
            "Arial Bold.ttf",
            "DejaVuSans-Bold.ttf",
            "impact.ttf",
        )
        if bold
        else (
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "arial.ttf",
            "Arial.ttf",
            "DejaVuSans.ttf",
        )
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


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _sanitize_filename(value: str) -> str:
    cleaned = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "_"
        for char in str(value or "").strip()
    )
    return cleaned.strip("._")[:120] or "unknown"
