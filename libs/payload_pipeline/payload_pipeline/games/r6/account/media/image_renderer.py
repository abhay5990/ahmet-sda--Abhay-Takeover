"""Shared image rendering helpers for typed R6 media generators."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import json
import logging
from pathlib import Path
import re
import unicodedata

logger = logging.getLogger(__name__)

from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests
from requests.adapters import HTTPAdapter


_SKIN_BACKGROUND = (211, 211, 211)
_OPERATOR_BACKGROUND = (255, 228, 225)
_CARD_BACKGROUND = (255, 255, 255)
_TEXT_COLOR = (0, 0, 0)
_SKIN_COLUMNS = 5
_OPERATOR_COLUMNS = 6
_BORDER_PADDING = 20
_BOTTOM_TEXT_AREA = 50
_SPACING = 10
_TOP_PADDING = 10
_BOTTOM_PADDING = 10
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
        if font_path is None:
            font_path = str(Path(_SHARED_RESOURCES_DIR) / "cmss10.ttf")
        if cache_base_dir is None:
            cache_base_dir = _DEFAULT_CACHE_BASE
        self.skins_json_path = skins_json_path
        self.operators_json_path = operators_json_path
        self.font_path = font_path
        self.cache_base_dir = Path(cache_base_dir)
        self.skin_cache_dir = self.cache_base_dir / "skins"
        self.operator_cache_dir = self.cache_base_dir / "operators"
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
                columns=_SKIN_COLUMNS,
                background=_SKIN_BACKGROUND,
                font_size=30,
                side_padding=0,
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
            image.save(save_path, "PNG")
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
            columns=_OPERATOR_COLUMNS,
            background=_OPERATOR_BACKGROUND,
            font_size=30,
            side_padding=20,
        )
        if image is None:
            return None

        save_path = output_dir / f"r6_operators.{self._sanitize_filename(product_id)}.png"
        image.save(save_path, "PNG")
        return str(save_path)

    def _resolve_output_dir(self, output_folder: str) -> Path:
        output_dir = Path(output_folder)
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def _render_collage(
        self,
        entries: list[R6ImageRenderEntry],
        *,
        columns: int,
        background: tuple[int, int, int],
        font_size: int,
        side_padding: int,
    ) -> Image.Image | None:
        cards: list[tuple[Image.Image, str]] = []
        for entry in entries:
            card_image = self._load_or_download_cached(entry)
            if card_image is None:
                continue
            cards.append((card_image, entry.title))

        if not cards:
            return None

        max_width = max(image.width for image, _ in cards)
        max_height = max(image.height for image, _ in cards)
        target_width = min(300, max_width)
        target_height = min(300, max_height)

        card_width = target_width + (_BORDER_PADDING * 2) + (side_padding * 2)
        card_height = target_height + (_BORDER_PADDING * 2) + _BOTTOM_TEXT_AREA

        rows = (len(cards) + columns - 1) // columns
        canvas_width = columns * card_width + max(0, columns - 1) * _SPACING
        canvas_height = (
            _TOP_PADDING
            + _BOTTOM_PADDING
            + rows * card_height
            + max(0, rows - 1) * _SPACING
        )

        canvas = Image.new("RGB", (canvas_width, canvas_height), background)

        x = 0
        y = _TOP_PADDING
        for index, (raw_image, title) in enumerate(cards, start=1):
            card = self._build_card(
                raw_image,
                title=title,
                card_width=card_width,
                card_height=card_height,
                target_width=target_width,
                target_height=target_height,
                font_size=font_size,
            )
            canvas.paste(card, (x, y))

            if index % columns == 0:
                x = 0
                y += card_height + _SPACING
            else:
                x += card_width + _SPACING

        return canvas

    def _build_card(
        self,
        image: Image.Image,
        *,
        title: str,
        card_width: int,
        card_height: int,
        target_width: int,
        target_height: int,
        font_size: int,
    ) -> Image.Image:
        card = Image.new("RGB", (card_width, card_height), _CARD_BACKGROUND)

        contained = ImageOps.contain(image, (target_width, target_height))
        image_x = (card_width - contained.width) // 2
        image_y = _BORDER_PADDING
        if contained.mode == "RGBA":
            card.paste(contained, (image_x, image_y), contained)
        else:
            card.paste(contained, (image_x, image_y))

        draw = ImageDraw.Draw(card)
        text_area = (
            _BORDER_PADDING,
            card_height - _BOTTOM_TEXT_AREA,
            card_width - _BORDER_PADDING,
            card_height,
        )
        self._draw_centered_text(draw, title, text_area, font_size)
        return card

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

        while current_size > 10:
            bbox = draw.textbbox((0, 0), text, font=font)
            if (bbox[2] - bbox[0]) <= max_width:
                break
            current_size -= 1
            font = self._load_font(current_size)

        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        text_x = x1 + (max_width - text_width) // 2
        text_y = y1 + ((y2 - y1) - text_height) // 2
        draw.text((text_x, text_y), text, fill=_TEXT_COLOR, font=font)

    def _load_or_download_cached(self, entry: R6ImageRenderEntry) -> Image.Image | None:
        current_cache_path = self._cache_path(entry.cache_key)
        cache_candidates = [current_cache_path, *self._legacy_cache_paths(entry.cache_key)]

        for candidate in cache_candidates:
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
        return [Path(base_dir) / folder / file_name for base_dir in _LEGACY_CACHE_DIRS]

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
            background = Image.new("RGBA", image.size, (255, 255, 255, 255))
            return Image.alpha_composite(background, image)
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

    def _load_font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        try:
            return ImageFont.truetype(self.font_path, size)
        except Exception as exc:
            logger.debug("Font load failed, using default: %s", exc)
            return ImageFont.load_default()

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
