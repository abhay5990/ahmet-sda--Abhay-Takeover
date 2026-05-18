"""Fortnite cosmetic grid renderer.

Generates polished grid images for each cosmetic type (skins, pickaxes,
dances, gliders) with rarity-based gradient card backgrounds, parallel
image fetching from the Fortnite API, and a professional header bar.

Image source
    https://fortnite-api.com/images/cosmetics/br/{id}/smallicon.png
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont
from requests.adapters import HTTPAdapter

from ..models import CosmeticItem
from .....shared.paths import default_cache_base_dir

logger = logging.getLogger(__name__)

# ── Fortnite rarity palette (top_color, bottom_color) ────────────────

_RARITY_PALETTE: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "legendary":  ((245, 155, 35),  (190, 90, 8)),
    "epic":       ((170, 65, 255),  (110, 18, 195)),
    "superrare":  ((210, 55, 140),  (152, 18, 88)),
    "rare":       ((68, 142, 212),  (28, 88, 175)),
    "uncommon":   ((92, 178, 62),   (50, 128, 28)),
    "common":     ((142, 142, 142), (95, 95, 95)),
}
_FALLBACK_GRAD = ((75, 75, 75), (50, 50, 50))

# ── Exclusive showcase palette ────────────────────────────────────
_EXCLUSIVE_GRAD = ((255, 215, 0), (218, 165, 32))  # gold top → gold bottom
_EXCLUSIVE_HEADER_BG = (28, 22, 8)
_EXCLUSIVE_ACCENT = (255, 215, 0)

_EXCLUSIVE_KEYWORDS: set[str] = {
    "renegade raider", "aerial assault trooper",
    "black knight", "royale knight", "blue squire", "sparkle specialist",
    "the reaper", "elite agent", "omega",
    "og ghoul trooper", "og skull trooper", "skull trooper", "ghoul trooper",
    "drift", "ragnarok",
    "travis scott", "galaxy", "ikonik", "wildcat", "honor guard", "wonder", "glow",
    "midas", "peely", "deadpool", "lara croft", "havoc",
    "take the l", "floss", "fresh", "orange justice",
    "leviathan axe", "mako", "reaper",
    "stw",
}
_EXCLUSIVE_RARITIES: set[str] = {
    "legendary", "mythic", "icon", "marvel", "dc", "starwars", "superrare",
}

_RARITY_ORDER = ("legendary", "epic", "superrare", "rare", "uncommon", "common")

# ── Layout ───────────────────────────────────────────────────────────

_CARD_W = 96
_CARD_H = 115
_ICON_MAX_W = int(_CARD_W * 1.22)
_ICON_MAX_H = _CARD_H - 2
_TEXT_H = 24
_LABEL_STRIP_H = 17
_LABEL_STRIP_ALPHA = 82
_GAP = 0
_MARGIN = 0
_HEADER_H = 72
_CORNER_R = 0
_BG_COLOR = (0, 0, 0)

# ── API ──────────────────────────────────────────────────────────────

_API_URL = "https://fortnite-api.com/images/cosmetics/br/{item_id}/smallicon.png"

# ── Type display info ────────────────────────────────────────────────

_TYPE_INFO: dict[str, tuple[str, str]] = {
    # type_key → (display_label, file_slug)
    "outfit":  ("Skins",    "skins"),
    "pickaxe": ("Pickaxes", "pickaxes"),
    "emote":   ("Dances",   "dances"),
    "glider":  ("Gliders",  "gliders"),
}

# ── Font cache ───────────────────────────────────────────────────────

_FONT_CACHE: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    for name in ("arial.ttf", "Arial.ttf", "arialbd.ttf", "DejaVuSans.ttf"):
        try:
            f = ImageFont.truetype(name, size)
            _FONT_CACHE[size] = f
            return f
        except (IOError, OSError):
            continue
    f = ImageFont.load_default()
    _FONT_CACHE[size] = f
    return f


def _bold_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = size + 10_000  # avoid collision with regular cache
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    for name in ("arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"):
        try:
            f = ImageFont.truetype(name, size)
            _FONT_CACHE[key] = f
            return f
        except (IOError, OSError):
            continue
    return _font(size)


def _title_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    key = size + 20_000
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    for name in (
        "Burbank Big Condensed Black.otf",
        "BurbankBigCondensed-Black.otf",
        "impact.ttf",
        "Impact.ttf",
        "ariblk.ttf",
        "Arial Black.ttf",
        "arialbd.ttf",
        "DejaVuSansCondensed-Bold.ttf",
        "DejaVuSans-Bold.ttf",
    ):
        try:
            f = ImageFont.truetype(name, size)
            _FONT_CACHE[key] = f
            return f
        except (IOError, OSError):
            continue
    return _bold_font(size)


class FortniteGridRenderer:
    """Render professional cosmetic grid images for Fortnite accounts."""

    def __init__(
        self,
        cache_dir: str | None = None,
        max_workers: int = 10,
    ) -> None:
        self._cache = Path(cache_dir or default_cache_base_dir("fortnite")) / "icons"
        self._cache.mkdir(parents=True, exist_ok=True)
        self._workers = max_workers
        self._session = self._build_session()

    # ── public API ────────────────────────────────────────────────────

    def render_exclusive(
        self,
        cosmetics: dict[str, list[CosmeticItem]],
        output_dir: str,
    ) -> str | None:
        """Render an exclusive showcase grid from all cosmetic types.

        Filters items by keyword/rarity, renders them with a gold palette,
        and returns the saved file path (or *None* if no exclusives found).
        """
        exclusives = self._collect_exclusives(cosmetics)
        if not exclusives:
            logger.info("No exclusive items found, skipping showcase")
            return None

        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        dest = str(out / "fortnite_exclusive.png")

        sorted_items = sorted(exclusives, key=self._rarity_sort_key)
        icon_map = self._fetch_all(sorted_items)
        cards = [self._render_exclusive_card(it, icon_map.get(it.id)) for it in sorted_items]

        cols = self._grid_columns(len(cards))
        rows = -(-len(cards) // cols)

        canvas_w = 2 * _MARGIN + cols * _CARD_W + max(0, cols - 1) * _GAP
        canvas_h = _HEADER_H + _MARGIN + rows * _CARD_H + max(0, rows - 1) * _GAP + _MARGIN

        canvas = Image.new("RGBA", (canvas_w, canvas_h), (*_EXCLUSIVE_HEADER_BG, 255))
        self._draw_exclusive_header(canvas, len(exclusives))

        for i, card in enumerate(cards):
            c, r = i % cols, i // cols
            x = _MARGIN + c * (_CARD_W + _GAP)
            y = _HEADER_H + _MARGIN + r * (_CARD_H + _GAP)
            canvas.paste(card, (x, y), card)

        try:
            final = canvas.convert("RGB")
            final.save(dest, "PNG", optimize=True)
            logger.info("Exclusive showcase saved -> %s (%d items)", dest, len(exclusives))
            return dest
        except Exception as exc:
            logger.error("Exclusive showcase save failed: %s", exc)
            return None

    def render_all(
        self,
        cosmetics: dict[str, list[CosmeticItem]],
        output_dir: str,
    ) -> list[str]:
        """Render a grid image per cosmetic type. Returns saved file paths."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        paths: list[str] = []
        for ctype, items in cosmetics.items():
            if not items:
                continue
            _, slug = _TYPE_INFO.get(ctype, (ctype, ctype))
            dest = str(out / f"fortnite_{slug}.png")
            result = self.render_type(items, ctype, dest)
            if result:
                paths.append(result)
        return paths

    def render_type(
        self,
        items: list[CosmeticItem],
        cosmetic_type: str,
        output_path: str,
    ) -> str | None:
        """Render a single grid image for one cosmetic type."""
        if not items:
            return None

        sorted_items = sorted(items, key=self._rarity_sort_key)

        # Parallel image fetch
        icon_map = self._fetch_all(sorted_items)

        # Build individual cards
        cards = [self._render_card(it, icon_map.get(it.id)) for it in sorted_items]

        # Grid dimensions
        cols = self._grid_columns(len(cards))
        rows = -(-len(cards) // cols)

        canvas_w = 2 * _MARGIN + cols * _CARD_W + max(0, cols - 1) * _GAP
        canvas_h = _HEADER_H + _MARGIN + rows * _CARD_H + max(0, rows - 1) * _GAP + _MARGIN

        canvas = Image.new("RGBA", (canvas_w, canvas_h), (*_BG_COLOR, 255))

        # Draw header
        self._draw_header(canvas, cosmetic_type, items)

        # Place cards onto canvas
        for i, card in enumerate(cards):
            c, r = i % cols, i // cols
            x = _MARGIN + c * (_CARD_W + _GAP)
            y = _HEADER_H + _MARGIN + r * (_CARD_H + _GAP)
            canvas.paste(card, (x, y), card)

        # Save
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            final = canvas.convert("RGB")
            final.save(output_path, "PNG", optimize=True)
            logger.info(
                "Fortnite %s grid saved → %s (%d items)",
                cosmetic_type, output_path, len(items),
            )
            return output_path
        except Exception as exc:
            logger.error("Grid save failed: %s", exc)
            return None

    # ── exclusive helpers ─────────────────────────────────────────────

    @staticmethod
    def _is_exclusive(item: CosmeticItem) -> bool:
        title_lower = item.title.lower()
        if any(kw in title_lower for kw in _EXCLUSIVE_KEYWORDS):
            return True
        return item.rarity in _EXCLUSIVE_RARITIES

    @staticmethod
    def _collect_exclusives(
        cosmetics: dict[str, list[CosmeticItem]],
    ) -> list[CosmeticItem]:
        seen: set[str] = set()
        result: list[CosmeticItem] = []
        for items in cosmetics.values():
            for item in items:
                if item.id not in seen and FortniteGridRenderer._is_exclusive(item):
                    seen.add(item.id)
                    result.append(item)
        return result

    def _render_exclusive_card(
        self, item: CosmeticItem, icon: Image.Image | None,
    ) -> Image.Image:
        """Card with gold gradient background for exclusive showcase."""
        card = _vertical_gradient_custom(
            _CARD_W, _CARD_H, _EXCLUSIVE_GRAD[0], _EXCLUSIVE_GRAD[1],
        ).convert("RGBA")

        if icon is not None:
            thumb = self._prepare_icon(icon)
            ix = (_CARD_W - thumb.width) // 2
            iy = _CARD_H - thumb.height
            card.paste(thumb, (ix, iy), thumb)

        overlay = Image.new("RGBA", card.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        strip_y = _CARD_H - _LABEL_STRIP_H
        overlay_draw.rectangle(
            [(0, strip_y), (_CARD_W, _CARD_H)],
            fill=(0, 0, 0, _LABEL_STRIP_ALPHA),
        )
        card = Image.alpha_composite(card, overlay)

        self._draw_card_name(card, item.title)
        return card

    @staticmethod
    def _draw_exclusive_header(canvas: Image.Image, count: int) -> None:
        draw = ImageDraw.Draw(canvas)
        title_font = _bold_font(28)
        label_font = _bold_font(16)

        x_start = _MARGIN + 8
        draw.text(
            (x_start, 10), str(count),
            font=title_font, fill=_EXCLUSIVE_ACCENT,
        )
        draw.text(
            (x_start, 42), "Exclusives",
            font=label_font, fill=(220, 200, 140, 255),
        )

        sep_y = _HEADER_H - 1
        draw.line(
            [(0, sep_y), (canvas.width, sep_y)],
            fill=(*_EXCLUSIVE_ACCENT, 80),
            width=1,
        )

    # ── card rendering ────────────────────────────────────────────────

    def _render_card(
        self, item: CosmeticItem, icon: Image.Image | None,
    ) -> Image.Image:
        """Build a single card: gradient bg + icon + name label."""
        # 1. Gradient background
        card = _vertical_gradient(_CARD_W, _CARD_H, item.rarity).convert("RGBA")

        # 2. Item icon, cropped from transparent padding and enlarged like LZT previews.
        if icon is not None:
            thumb = self._prepare_icon(icon)
            ix = (_CARD_W - thumb.width) // 2
            iy = _CARD_H - thumb.height
            card.paste(thumb, (ix, iy), thumb)

        # 3. Subtle full-width strip behind the title for readability.
        overlay = Image.new("RGBA", card.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        strip_y = _CARD_H - _LABEL_STRIP_H
        overlay_draw.rectangle(
            [(0, strip_y), (_CARD_W, _CARD_H)],
            fill=(0, 0, 0, _LABEL_STRIP_ALPHA),
        )
        card = Image.alpha_composite(card, overlay)

        # 4. Item name overlaid directly on the artwork.
        self._draw_card_name(card, item.title)

        return card

    @staticmethod
    def _prepare_icon(icon: Image.Image) -> Image.Image:
        """Trim transparent padding and return an enlarged, horizontally clipped icon."""
        thumb = icon.copy().convert("RGBA")
        alpha_bbox = thumb.getchannel("A").getbbox()
        if alpha_bbox:
            thumb = thumb.crop(alpha_bbox)

        thumb.thumbnail((_ICON_MAX_W, _ICON_MAX_H), Image.Resampling.LANCZOS)
        if thumb.width > _CARD_W:
            left = (thumb.width - _CARD_W) // 2
            thumb = thumb.crop((left, 0, left + _CARD_W, thumb.height))
        return thumb

    @staticmethod
    def _draw_card_name(card: Image.Image, title: str) -> None:
        """Auto-size and draw the item name over the card art."""
        name = title.upper()
        max_text_w = _CARD_W - 4

        # Try decreasing bold font sizes until text fits
        probe = ImageDraw.Draw(card)
        chosen_size = 8
        chosen_font = _title_font(8)
        for size in (12, 11, 10, 9, 8):
            candidate = _title_font(size)
            bbox = probe.textbbox((0, 0), name, font=candidate)
            if (bbox[2] - bbox[0]) <= max_text_w:
                chosen_size = size
                chosen_font = candidate
                break
            if size == 8:
                chosen_size = size
                chosen_font = candidate

        # Truncate if still too wide at minimum size
        bbox = probe.textbbox((0, 0), name, font=chosen_font)
        tw = bbox[2] - bbox[0]
        while tw > max_text_w and len(name) > 4:
            name = name[:-3] + ".."
            bbox = probe.textbbox((0, 0), name, font=chosen_font)
            tw = bbox[2] - bbox[0]

        th = bbox[3] - bbox[1]
        tx = (_CARD_W - tw) // 2
        ty = _CARD_H - th - 4

        scale = 3
        text_layer = Image.new(
            "RGBA",
            (_CARD_W * scale, _CARD_H * scale),
            (0, 0, 0, 0),
        )
        text_draw = ImageDraw.Draw(text_layer)
        hi_font = _title_font(chosen_size * scale)
        shadow = (0, 0, 0, 220)
        outline = scale
        sx = tx * scale
        sy = ty * scale
        text_draw.text(
            (sx, sy),
            name,
            font=hi_font,
            fill=(255, 255, 255, 255),
            stroke_width=outline,
            stroke_fill=shadow,
        )
        text_layer = text_layer.resize(card.size, Image.Resampling.LANCZOS)
        card.alpha_composite(text_layer)

    # ── header ────────────────────────────────────────────────────────

    @staticmethod
    def _draw_header(
        canvas: Image.Image, cosmetic_type: str, items: list[CosmeticItem],
    ) -> None:
        draw = ImageDraw.Draw(canvas)
        label, _ = _TYPE_INFO.get(cosmetic_type, (cosmetic_type.title(), ""))

        total = len(items)
        shop_count = sum(1 for it in items if it.from_shop)

        title_font = _bold_font(28)
        label_font = _bold_font(16)

        # Count: "69 (15)"
        count_str = f"{total} ({shop_count})"
        x_start = _MARGIN + 8

        draw.text((x_start, 10), count_str, font=title_font, fill=(255, 255, 255, 255))
        draw.text((x_start, 42), label, font=label_font, fill=(220, 220, 230, 255))

        # Thin separator line
        sep_y = _HEADER_H - 1
        draw.line(
            [(0, sep_y), (canvas.width, sep_y)],
            fill=(30, 30, 30, 180),
            width=1,
        )

    # ── parallel image fetching ───────────────────────────────────────

    def _fetch_all(
        self, items: list[CosmeticItem],
    ) -> dict[str, Image.Image]:
        result: dict[str, Image.Image] = {}
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            futures = {
                pool.submit(self._fetch_icon, it.id): it.id for it in items
            }
            for fut in as_completed(futures):
                item_id = futures[fut]
                try:
                    img = fut.result()
                    if img is not None:
                        result[item_id] = img
                except Exception:
                    pass

        logger.info("Fetched %d / %d cosmetic icons", len(result), len(items))
        return result

    def _fetch_icon(self, item_id: str) -> Image.Image | None:
        """Fetch a single icon with file-based caching."""
        cached = self._cache / f"{item_id}.png"

        if cached.exists():
            try:
                return Image.open(cached).convert("RGBA")
            except Exception:
                cached.unlink(missing_ok=True)

        url = _API_URL.format(item_id=item_id)
        try:
            resp = self._session.get(url, timeout=15)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGBA")
            img.save(cached, "PNG")
            return img
        except Exception as exc:
            logger.debug("Icon fetch failed for %s: %s", item_id, exc)
            return None

    # ── helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _rarity_sort_key(item: CosmeticItem) -> int:
        try:
            return _RARITY_ORDER.index(item.rarity)
        except ValueError:
            return len(_RARITY_ORDER)

    @staticmethod
    def _grid_columns(item_count: int) -> int:
        """Choose the column count whose final canvas is closest to square."""
        if item_count <= 0:
            return 0

        best_cols = 1
        best_score = float("inf")
        for cols in range(1, item_count + 1):
            rows = -(-item_count // cols)
            width = 2 * _MARGIN + cols * _CARD_W + max(0, cols - 1) * _GAP
            height = (
                _HEADER_H
                + _MARGIN
                + rows * _CARD_H
                + max(0, rows - 1) * _GAP
                + _MARGIN
            )
            score = abs(math.log(width / height))
            if score < best_score:
                best_cols = cols
                best_score = score
        return best_cols

    @staticmethod
    def _build_session() -> requests.Session:
        s = requests.Session()
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        return s


# ── module-level drawing utilities ───────────────────────────────────


def _vertical_gradient(
    w: int, h: int, rarity: str,
) -> Image.Image:
    """Create a vertical gradient from rarity top-color to bottom-color."""
    top, bot = _RARITY_PALETTE.get(rarity, _FALLBACK_GRAD)
    # Build a 1px-wide strip then stretch — fast and smooth
    strip = Image.new("RGB", (1, 256))
    px = strip.load()
    for y in range(256):
        t = y / 255.0
        px[0, y] = (
            int(top[0] + (bot[0] - top[0]) * t),
            int(top[1] + (bot[1] - top[1]) * t),
            int(top[2] + (bot[2] - top[2]) * t),
        )
    return strip.resize((w, h), Image.Resampling.BILINEAR)


def _vertical_gradient_custom(
    w: int, h: int,
    top: tuple[int, int, int],
    bot: tuple[int, int, int],
) -> Image.Image:
    """Create a vertical gradient from arbitrary top/bottom colours."""
    strip = Image.new("RGB", (1, 256))
    px = strip.load()
    for y in range(256):
        t = y / 255.0
        px[0, y] = (
            int(top[0] + (bot[0] - top[0]) * t),
            int(top[1] + (bot[1] - top[1]) * t),
            int(top[2] + (bot[2] - top[2]) * t),
        )
    return strip.resize((w, h), Image.Resampling.BILINEAR)


def _apply_rounded_corners(img: Image.Image, radius: int) -> Image.Image:
    """Apply rounded corners via an alpha mask."""
    if img.mode != "RGBA":
        img = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [(0, 0), (img.width - 1, img.height - 1)],
        radius=radius,
        fill=255,
    )
    img.putalpha(mask)
    return img
