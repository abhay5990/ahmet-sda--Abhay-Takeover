"""Shared image rendering helpers for typed R6 media generators."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import logging
import math
from pathlib import Path
import re
import unicodedata

logger = logging.getLogger(__name__)

from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests
from requests.adapters import HTTPAdapter


_SKIN_BACKGROUND = (13, 15, 20)
_OPERATOR_BACKGROUND = (16, 14, 21)
_CARD_BACKGROUND = (25, 28, 34, 255)
_CARD_BORDER = (70, 76, 88, 255)
_CARD_HIGHLIGHT = (255, 190, 70, 255)
_LABEL_BACKGROUND = (0, 0, 0, 150)
_TEXT_COLOR = (244, 247, 250, 255)
_MUTED_TEXT_COLOR = (178, 186, 198, 255)
_PLACEHOLDER_FILL = (35, 39, 47, 255)
_PLACEHOLDER_BORDER = (96, 104, 120, 255)

# MD5 hashes of known LZT/nztcdn placeholder images (saved as PNG by Pillow).
# A cached file matching any of these is treated as poisoned and re-fetched.
_POISONED_CACHE_MD5S: frozenset[str] = frozenset({
    "03859bc548c53f5ed5418b8f67cbaa46",
})
_GAP = 5
_TOP_PADDING = 14
_BOTTOM_PADDING = 10
_HEADER_HEIGHT = 78
_CARD_RADIUS = 7
_CACHE_VERSION = "v2"
_SKIN_SPLIT_THRESHOLDS = (
    (300, 3),
    (160, 2),
)
from .....shared.paths import default_cache_base_dir, default_media_output_dir

_SLICE_RESOURCES_DIR = str(Path(__file__).resolve().parent.parent / "resources")
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent  # payload_pipeline/
_SHARED_RESOURCES_DIR = str(_PACKAGE_ROOT / "shared" / "resources")
_DEFAULT_CACHE_BASE = default_cache_base_dir("rainbow-six-siege")
_DEFAULT_R6_OUTPUT_DIR = default_media_output_dir("rainbow-six-siege")

_LEGACY_CACHE_DIRS = (
    "assets/rainbow/cache_images",
    "assets/rainbow/cache-images",
    "assets/r6/cache_images",
)


@dataclass(slots=True)
class R6ImageRenderEntry:
    """One cached or remotely downloadable media asset."""

    cache_key: str
    title: str
    image_urls: list[str]


@dataclass(frozen=True, slots=True)
class _R6RenderLayout:
    """Canvas layout for one R6 inventory media type."""

    max_columns: int
    card_width: int
    card_height: int
    image_box: tuple[int, int]
    image_top: int
    label_height: int
    font_size: int


_COMPACT_SKIN_LAYOUT = _R6RenderLayout(
    max_columns=15,
    card_width=192,
    card_height=124,
    image_box=(176, 72),
    image_top=8,
    label_height=30,
    font_size=12,
)
_READABLE_SKIN_LAYOUT = _R6RenderLayout(
    max_columns=12,
    card_width=220,
    card_height=140,
    image_box=(206, 78),
    image_top=8,
    label_height=34,
    font_size=15,
)
_SKIN_LAYOUT = _COMPACT_SKIN_LAYOUT
_OPERATOR_LAYOUT = _R6RenderLayout(
    max_columns=8,
    card_width=176,
    card_height=196,
    image_box=(140, 140),
    image_top=13,
    label_height=32,
    font_size=17,
)

_FONT_CACHE: dict[tuple[str, bool, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


class R6ImageRenderer:
    """Cache, download, and collage rendering shared by R6 image generators."""

    def __init__(
        self,
        *,
        skins_json_path: str | None = None,
        operators_json_path: str | None = None,
        font_path: str | None = None,
        cache_base_dir: str | None = None,
    ) -> None:
        if skins_json_path is None:
            skins_json_path = str(Path(_SLICE_RESOURCES_DIR) / "RainbowSkins.json")
        if operators_json_path is None:
            operators_json_path = str(Path(_SLICE_RESOURCES_DIR) / "RainbowOperators.json")
        if cache_base_dir is None:
            cache_base_dir = _DEFAULT_CACHE_BASE
        self.skins_json_path = skins_json_path
        self.operators_json_path = operators_json_path
        self.font_path = font_path
        self.fallback_font_path = str(Path(_SHARED_RESOURCES_DIR) / "cmss10.ttf")
        self.cache_base_dir = Path(cache_base_dir)
        self.skin_cache_dir = self.cache_base_dir / f"skins_{_CACHE_VERSION}"
        self.operator_cache_dir = self.cache_base_dir / f"operators_{_CACHE_VERSION}"
        self.skin_cache_dir.mkdir(parents=True, exist_ok=True)
        self.operator_cache_dir.mkdir(parents=True, exist_ok=True)
        self._skins_by_id: dict[str, R6ImageRenderEntry] | None = None
        self._skins_by_name: dict[str, R6ImageRenderEntry] | None = None
        self._operators_by_name: dict[str, R6ImageRenderEntry] | None = None
        self._session = requests.Session()
        self._session.mount("https://", HTTPAdapter(pool_connections=5, pool_maxsize=10))
        self._session.mount("http://", HTTPAdapter(pool_connections=2, pool_maxsize=5))

    def render_skin_entries(
        self,
        entries: list[R6ImageRenderEntry],
        *,
        product_id: str,
        output_folder: str,
    ) -> list[str]:
        output_dir = self._resolve_output_dir(output_folder)
        if not entries:
            return []

        split_count = self._resolve_skin_split_count(len(entries))
        chunks = self._split_entries(entries, split_count)
        created: list[str] = []

        for index, chunk in enumerate(chunks, start=1):
            if not chunk:
                continue

            image = self._render_collage(
                chunk,
                layout=_SKIN_LAYOUT,
                background=_SKIN_BACKGROUND,
                heading="Weapon Skins",
            )
            if image is None:
                continue

            if split_count == 1:
                filename = f"rainbow_skins.{self._sanitize_filename(product_id)}.png"
            else:
                filename = (
                    "rainbow_skins."
                    f"{self._sanitize_filename(product_id)}_part{index}of{split_count}.png"
                )

            save_path = output_dir / filename
            image.convert("RGB").save(save_path, "PNG", optimize=True)
            created.append(str(save_path))

        return created

    def render_operator_entries(
        self,
        entries: list[R6ImageRenderEntry],
        *,
        product_id: str,
        output_folder: str,
    ) -> str | None:
        output_dir = self._resolve_output_dir(output_folder)
        if not entries:
            return None

        image = self._render_collage(
            entries,
            layout=_OPERATOR_LAYOUT,
            background=_OPERATOR_BACKGROUND,
            heading="Operators",
        )
        if image is None:
            return None

        save_path = output_dir / f"r6_operators.{self._sanitize_filename(product_id)}.png"
        image.convert("RGB").save(save_path, "PNG", optimize=True)
        return str(save_path)

    def _resolve_output_dir(self, output_folder: str) -> Path:
        output_dir = Path(output_folder)
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _render_collage(
        self,
        entries: list[R6ImageRenderEntry],
        *,
        layout: _R6RenderLayout,
        background: tuple[int, int, int],
        heading: str,
    ) -> Image.Image | None:
        cards: list[tuple[Image.Image | None, str]] = []
        for entry in entries:
            card_image = self._load_or_download_cached(entry)
            cards.append((card_image, entry.title))

        if not cards:
            return None

        effective_columns = self._grid_columns(len(cards), layout)
        rows = (len(cards) + effective_columns - 1) // effective_columns
        canvas_width = (
            effective_columns * layout.card_width
            + max(0, effective_columns - 1) * _GAP
        )
        canvas_height = (
            _HEADER_HEIGHT
            + _TOP_PADDING
            + _BOTTOM_PADDING
            + rows * layout.card_height
            + max(0, rows - 1) * _GAP
        )

        canvas = self._create_canvas(canvas_width, canvas_height, background)
        self._draw_header(canvas, heading=heading, count=len(cards))

        x = 0
        y = _HEADER_HEIGHT + _TOP_PADDING
        for index, (raw_image, title) in enumerate(cards, start=1):
            card = self._build_card(
                raw_image,
                title=title,
                layout=layout,
            )
            canvas.alpha_composite(card, (x, y))

            if index % effective_columns == 0:
                x = 0
                y += layout.card_height + _GAP
            else:
                x += layout.card_width + _GAP

        return canvas

    @staticmethod
    def _grid_columns(item_count: int, layout: _R6RenderLayout) -> int:
        if item_count <= 0:
            return 1

        best_columns = 1
        best_score = float("inf")
        max_columns = max(1, min(item_count, layout.max_columns))
        for columns in range(1, max_columns + 1):
            rows = math.ceil(item_count / columns)
            width = columns * layout.card_width + max(0, columns - 1) * _GAP
            height = (
                _HEADER_HEIGHT
                + _TOP_PADDING
                + _BOTTOM_PADDING
                + rows * layout.card_height
                + max(0, rows - 1) * _GAP
            )
            score = abs(math.log(width / height))
            if score < best_score:
                best_columns = columns
                best_score = score

        return best_columns

    def _create_canvas(
        self,
        width: int,
        height: int,
        background: tuple[int, int, int],
    ) -> Image.Image:
        top = tuple(min(255, channel + 12) for channel in background)
        bottom = tuple(max(0, channel - 4) for channel in background)
        strip = Image.new("RGB", (1, 256))
        pixels = strip.load()
        for y in range(256):
            ratio = y / 255.0
            pixels[0, y] = (
                int(top[0] + (bottom[0] - top[0]) * ratio),
                int(top[1] + (bottom[1] - top[1]) * ratio),
                int(top[2] + (bottom[2] - top[2]) * ratio),
            )
        return strip.resize((width, height), Image.Resampling.BILINEAR).convert("RGBA")

    def _draw_header(self, canvas: Image.Image, *, heading: str, count: int) -> None:
        draw = ImageDraw.Draw(canvas)
        title_font = self._load_font(34, bold=True)
        subtitle_font = self._load_font(16)

        title = f"{count} {heading}"
        subtitle = "Rainbow Six Siege Inventory"
        draw.text(
            (16, 12),
            title,
            font=title_font,
            fill=_TEXT_COLOR,
            stroke_width=1,
            stroke_fill=(0, 0, 0, 180),
        )
        draw.text((18, 50), subtitle, font=subtitle_font, fill=_MUTED_TEXT_COLOR)
        draw.line(
            [(0, _HEADER_HEIGHT - 1), (canvas.width, _HEADER_HEIGHT - 1)],
            fill=(255, 255, 255, 34),
            width=1,
        )

    def _build_card(
        self,
        image: Image.Image | None,
        *,
        title: str,
        layout: _R6RenderLayout,
    ) -> Image.Image:
        card_width = layout.card_width
        card_height = layout.card_height
        card = Image.new("RGBA", (card_width, card_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(card)
        draw.rounded_rectangle(
            [(0, 0), (card_width - 1, card_height - 1)],
            radius=_CARD_RADIUS,
            fill=_CARD_BACKGROUND,
            outline=_CARD_BORDER,
            width=1,
        )
        draw.line(
            [(_CARD_RADIUS, 1), (card_width - _CARD_RADIUS, 1)],
            fill=_CARD_HIGHLIGHT,
            width=1,
        )

        if image is None:
            self._draw_placeholder(card, title=title, layout=layout)
        else:
            contained = self._prepare_card_image(image, layout.image_box)
            image_x = (card_width - contained.width) // 2
            image_y = layout.image_top + (layout.image_box[1] - contained.height) // 2
            if contained.mode == "RGBA":
                card.paste(contained, (image_x, image_y), contained)
            else:
                card.paste(contained, (image_x, image_y))

        label_overlay = Image.new("RGBA", card.size, (0, 0, 0, 0))
        label_draw = ImageDraw.Draw(label_overlay)
        label_y = card_height - layout.label_height
        label_draw.rounded_rectangle(
            [
                (4, label_y + 2),
                (card_width - 4, card_height - 5),
            ],
            radius=5,
            fill=_LABEL_BACKGROUND,
        )
        card.alpha_composite(label_overlay)

        draw = ImageDraw.Draw(card)
        text_area = (
            8,
            label_y,
            card_width - 8,
            card_height - 1,
        )
        self._draw_centered_text(draw, title, text_area, layout.font_size)
        return card

    @staticmethod
    def _prepare_card_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
        prepared = image.copy().convert("RGBA")
        alpha_bbox = prepared.getchannel("A").getbbox()
        if alpha_bbox:
            prepared = prepared.crop(alpha_bbox)
        return ImageOps.contain(prepared, size, method=Image.Resampling.LANCZOS)

    def _draw_placeholder(
        self,
        card: Image.Image,
        *,
        title: str,
        layout: _R6RenderLayout,
    ) -> None:
        draw = ImageDraw.Draw(card)
        box_width, box_height = layout.image_box
        x1 = (layout.card_width - box_width) // 2
        y1 = layout.image_top
        x2 = x1 + box_width
        y2 = y1 + box_height
        draw.rounded_rectangle(
            [(x1, y1), (x2, y2)],
            radius=5,
            fill=_PLACEHOLDER_FILL,
            outline=_PLACEHOLDER_BORDER,
            width=1,
        )

        initials = "".join(part[:1] for part in title.split()[:2]).upper() or "R6"
        font = self._load_font(max(18, min(28, box_height // 2)), bold=True)
        bbox = draw.textbbox((0, 0), initials, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        draw.text(
            (
                x1 + (box_width - text_width) // 2 - bbox[0],
                y1 + (box_height - text_height) // 2 - bbox[1] - 1,
            ),
            initials,
            font=font,
            fill=_MUTED_TEXT_COLOR,
        )

    def _draw_centered_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        area: tuple[int, int, int, int],
        font_size: int,
    ) -> None:
        x1, y1, x2, y2 = area
        max_width = x2 - x1
        font = self._load_font(font_size)
        current_size = font_size

        while current_size > 8:
            bbox = draw.textbbox((0, 0), text, font=font)
            if (bbox[2] - bbox[0]) <= max_width:
                break
            current_size -= 1
            font = self._load_font(current_size)

        bbox = draw.textbbox((0, 0), text, font=font)
        while (bbox[2] - bbox[0]) > max_width and len(text) > 4:
            text = text[:-4].rstrip() + "..."
            bbox = draw.textbbox((0, 0), text, font=font)

        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        text_x = x1 + (max_width - text_width) // 2 - bbox[0]
        text_y = y1 + ((y2 - y1) - text_height) // 2 - bbox[1] - 2
        draw.text(
            (text_x, text_y),
            text,
            fill=_TEXT_COLOR,
            font=font,
            stroke_width=1,
            stroke_fill=(0, 0, 0, 190),
        )

    def _load_or_download_cached(self, entry: R6ImageRenderEntry) -> Image.Image | None:
        current_cache_path = self._cache_path(entry.cache_key)
        cache_candidates = [current_cache_path, *self._legacy_cache_paths(entry.cache_key)]

        for candidate in cache_candidates:
            if self._is_poisoned_cache(candidate):
                logger.debug("Skipping poisoned cache file: %s", candidate)
                continue
            image = self._load_cached_image(candidate)
            if image is not None:
                return image

        for url in entry.image_urls:
            image = self._download_image(url)
            if image is None:
                continue
            try:
                image.save(current_cache_path, "PNG")
            except Exception as exc:
                logger.debug("Cache write failed for %s: %s", current_cache_path, exc)
            return image

        return None

    def _is_poisoned_cache(self, path: Path) -> bool:
        """Return True if the file is a known LZT placeholder cached on disk."""
        if not path.exists():
            return False
        try:
            md5 = hashlib.md5(path.read_bytes()).hexdigest()
            return md5 in _POISONED_CACHE_MD5S
        except Exception:
            return False

    def _cache_path(self, cache_key: str) -> Path:
        if cache_key.startswith("operator:"):
            safe_name = self._sanitize_filename(cache_key.removeprefix("operator:"))
            return self.operator_cache_dir / f"operator_{safe_name}.png"

        safe_name = self._sanitize_filename(cache_key.removeprefix("skin:"))
        return self.skin_cache_dir / f"skin_{safe_name}.png"

    def _legacy_cache_paths(self, cache_key: str) -> list[Path]:
        folder = "operators" if cache_key.startswith("operator:") else "skins"
        if cache_key.startswith("operator:"):
            safe_name = self._sanitize_filename(cache_key.removeprefix("operator:"))
            file_name = f"operator_{safe_name}.png"
        else:
            safe_name = self._sanitize_filename(cache_key.removeprefix("skin:"))
            file_name = f"skin_{safe_name}.png"
        return [
            self.cache_base_dir / folder / file_name,
            *[Path(base_dir) / folder / file_name for base_dir in _LEGACY_CACHE_DIRS],
        ]

    def _load_cached_image(self, path: Path) -> Image.Image | None:
        if not path.exists():
            return None
        try:
            image = Image.open(path)
            return image.convert("RGBA")
        except Exception as exc:
            logger.debug("Failed to load image from %s: %s", path, exc)
            return None

    def _download_image(self, url: str) -> Image.Image | None:
        try:
            response = self._session.get(url, timeout=(10, 30))
            response.raise_for_status()
            if len(response.content) < 100:
                return None

            image = Image.open(BytesIO(response.content)).convert("RGBA")
            image.load()
            return image
        except Exception as exc:
            logger.debug("Failed to download image from %s: %s", url, exc)
            return None

    def _load_skins_by_id(self) -> dict[str, R6ImageRenderEntry]:
        if self._skins_by_id is not None:
            return self._skins_by_id

        raw_data = self._load_json(self._resolve_skins_json_path())
        by_id: dict[str, R6ImageRenderEntry] = {}
        by_name: dict[str, R6ImageRenderEntry] = {}

        if isinstance(raw_data, list):
            for item in raw_data:
                if not isinstance(item, dict):
                    continue
                skin_id = str(item.get("data_id") or "").strip()
                image_url = str(item.get("src") or "").strip()
                title = str(item.get("alt") or "").strip() or "No Title"
                if not image_url:
                    continue

                entry = R6ImageRenderEntry(
                    cache_key=f"skin:{skin_id or self._normalize_name(title).replace(' ', '_')}",
                    title=title,
                    image_urls=[image_url],
                )
                if skin_id and skin_id not in by_id:
                    by_id[skin_id] = entry

                normalized = self._normalize_name(title)
                if normalized and normalized not in by_name:
                    by_name[normalized] = entry

        self._skins_by_id = by_id
        self._skins_by_name = by_name
        return self._skins_by_id

    def _load_skins_by_name(self) -> dict[str, R6ImageRenderEntry]:
        if self._skins_by_name is None:
            self._load_skins_by_id()
        return self._skins_by_name or {}

    def _load_operators_by_name(self) -> dict[str, R6ImageRenderEntry]:
        if self._operators_by_name is not None:
            return self._operators_by_name

        raw_data = self._load_json(self._resolve_operators_json_path())
        catalog: dict[str, R6ImageRenderEntry] = {}
        if isinstance(raw_data, list):
            for item in raw_data:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                image_url = str(item.get("img") or "").strip()
                if not name or not image_url:
                    continue

                normalized = self._normalize_name(name)
                if not normalized or normalized in catalog:
                    continue

                catalog[normalized] = R6ImageRenderEntry(
                    cache_key=f"operator:{normalized}",
                    title=name,
                    image_urls=[image_url],
                )

        self._operators_by_name = catalog
        return self._operators_by_name

    def _resolve_skins_json_path(self) -> str:
        """Resolve skins JSON; primary is __file__-relative, legacy CWD fallbacks."""
        for candidate in (
            self.skins_json_path,
            "assets/r6/RainbowSkins.json",
            "assets/rainbow/RainbowSkins.json",
        ):
            if candidate and Path(candidate).exists():
                return candidate
        return self.skins_json_path

    def _resolve_operators_json_path(self) -> str:
        """Resolve operators JSON; primary is __file__-relative, legacy CWD fallbacks."""
        for candidate in (
            self.operators_json_path,
            "assets/r6/RainbowOperators.json",
            "assets/rainbow/RainbowOperators.json",
        ):
            if candidate and Path(candidate).exists():
                return candidate
        return self.operators_json_path

    def _load_json(self, path: str) -> object:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception as exc:
            logger.debug("Failed to load JSON from %s: %s", path, exc)
            return {}

    def _load_font(
        self,
        size: int,
        *,
        bold: bool = False,
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        key = (self.font_path or "", bold, size)
        cached = _FONT_CACHE.get(key)
        if cached is not None:
            return cached

        candidates: list[str] = []
        if self.font_path:
            candidates.append(self.font_path)
        if bold:
            candidates.extend(
                [
                    "C:/Windows/Fonts/arialbd.ttf",
                    "C:/Windows/Fonts/segoeuib.ttf",
                    "arialbd.ttf",
                    "Arial Bold.ttf",
                    "DejaVuSans-Bold.ttf",
                ]
            )
        else:
            candidates.extend(
                [
                    "C:/Windows/Fonts/arial.ttf",
                    "C:/Windows/Fonts/segoeui.ttf",
                    "arial.ttf",
                    "Arial.ttf",
                    "DejaVuSans.ttf",
                ]
            )
        candidates.append(self.fallback_font_path)

        for candidate in candidates:
            try:
                font = ImageFont.truetype(candidate, size)
                _FONT_CACHE[key] = font
                return font
            except Exception:
                continue

        font = ImageFont.load_default()
        _FONT_CACHE[key] = font
        return font

    def _resolve_skin_split_count(self, skin_count: int) -> int:
        for threshold, split_count in _SKIN_SPLIT_THRESHOLDS:
            if skin_count >= threshold:
                return split_count
        return 1

    def _split_entries(
        self,
        entries: list[R6ImageRenderEntry],
        split_count: int,
    ) -> list[list[R6ImageRenderEntry]]:
        if split_count <= 1:
            return [entries]

        base = len(entries) // split_count
        remainder = len(entries) % split_count
        chunks: list[list[R6ImageRenderEntry]] = []
        start = 0
        for index in range(split_count):
            size = base + (1 if index < remainder else 0)
            end = start + size
            chunks.append(entries[start:end])
            start = end
        return chunks

    def _sanitize_filename(self, value: str) -> str:
        cleaned = re.sub(r"[^\w\-]+", "_", value.strip(), flags=re.ASCII)
        cleaned = cleaned.strip("_")
        return cleaned[:120] or "unknown"

    def _normalize_name(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        normalized = normalized.lower().strip()
        normalized = normalized.replace("&", " and ")
        normalized = re.sub(r"\([^)]*\)", " ", normalized)
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized
