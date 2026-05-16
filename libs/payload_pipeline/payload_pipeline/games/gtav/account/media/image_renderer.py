"""Generated GTA V account card renderer."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..models import GtavResolvedAccount

RENDERER_VERSION = "gtav-account-card-v1"

_MEDIA_DIR = Path(__file__).resolve().parents[1] / "resources" / "media"
_BACKGROUND_PATH = _MEDIA_DIR / "background.png"
_W, _H = 1254, 1254

_WHITE = (248, 248, 250, 255)
_BLACK = (0, 0, 0, 210)
_GOLD = (255, 207, 72, 255)
_GOLD_SOFT = (255, 224, 125, 255)
_PURPLE = (185, 68, 255, 255)
_CYAN = (80, 205, 255, 255)
_GREEN = (80, 235, 95, 255)


@dataclass(frozen=True, slots=True)
class GtavCardData:
    """Public fields that are allowed to appear on the generated card."""

    title: str
    platform: str
    cash_label: str
    cars_label: str
    rank_label: str
    tags: tuple[str, ...]
    delivery_text: str

    @classmethod
    def from_account(cls, account: GtavResolvedAccount, *, delivery_text: str) -> "GtavCardData":
        cash_unit = (account.cash_unit or "Million").strip()
        cash_label = (
            f"{account.cash_amount} {cash_unit} Cash"
            if account.cash_amount
            else "Cash Included"
        )
        cars_label = (
            f"{account.cars_count} Modded Cars"
            if account.cars_count
            else "Modded Cars"
        )
        rank_label = f"Rank {account.level} RP" if account.level else "Rank Ready"

        tags = _normalize_tags(account)

        return cls(
            title="GTA Online Account",
            platform=(account.main_platform or "GTA V").strip(),
            cash_label=cash_label,
            cars_label=cars_label,
            rank_label=rank_label,
            tags=tuple(tags),
            delivery_text=delivery_text,
        )


class GtavAccountCardRenderer:
    """Render one deterministic premium account card image."""

    def __init__(
        self,
        *,
        background_path: Path | str = _BACKGROUND_PATH,
    ) -> None:
        self.background_path = Path(background_path)
        self._icon_cache: dict[tuple[str, int], Image.Image] = {}

    def fingerprint(self, data: GtavCardData) -> str:
        payload = {
            "renderer": RENDERER_VERSION,
            "data": asdict(data),
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def render(self, data: GtavCardData, output_path: str | Path) -> str:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        canvas = self._load_background()
        canvas = self._add_left_readability(canvas)

        draw = ImageDraw.Draw(canvas)
        self._draw_header(canvas, draw, data)
        next_y = self._draw_metric_rows(canvas, data, start_y=220)
        next_y = self._draw_tags(canvas, data.tags, start_y=next_y + 16)
        self._draw_delivery(canvas, data.delivery_text, start_y=max(next_y + 26, 1015))

        final = Image.new("RGB", canvas.size, (8, 9, 16))
        final.paste(canvas, mask=canvas.split()[3])
        final.save(output, format="PNG", optimize=True)
        return str(output)

    def _load_background(self) -> Image.Image:
        if self.background_path.is_file():
            image = Image.open(self.background_path).convert("RGBA")
            return _crop_and_resize(image, (_W, _H))
        return Image.new("RGBA", (_W, _H), (8, 9, 16, 255))

    def _add_left_readability(self, canvas: Image.Image) -> Image.Image:
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for x in range(760):
            t = 1 - (x / 760) ** 0.72
            alpha = int(230 * t)
            draw.line([(x, 0), (x, _H)], fill=(2, 4, 13, alpha))

        panel = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        panel_draw = ImageDraw.Draw(panel)
        panel_draw.rounded_rectangle(
            [34, 28, 735, 1216],
            radius=28,
            fill=(5, 7, 18, 128),
            outline=(190, 64, 255, 118),
            width=2,
        )
        panel = panel.filter(ImageFilter.GaussianBlur(0.2))
        return Image.alpha_composite(Image.alpha_composite(canvas, layer), panel)

    def _draw_header(self, canvas: Image.Image, draw: ImageDraw.ImageDraw, data: GtavCardData) -> None:
        platform_font = _fit_font(draw, data.platform.upper(), 600, start_size=76, min_size=42, bold=True)
        title_font = _fit_font(draw, data.title.upper(), 620, start_size=58, min_size=36, bold=True)

        _draw_glow_text(
            canvas,
            (62, 52),
            data.platform.upper(),
            platform_font,
            fill=_PURPLE,
            stroke_width=3,
            stroke_fill=_BLACK,
            glow_fill=(185, 68, 255, 95),
            glow_blur=13,
        )
        _draw_glow_text(
            canvas,
            (64, 128),
            data.title.upper(),
            title_font,
            fill=_GOLD,
            stroke_width=3,
            stroke_fill=_BLACK,
            glow_fill=(255, 207, 72, 80),
            glow_blur=10,
        )

        draw = ImageDraw.Draw(canvas)
        draw.line([(64, 198), (690, 198)], fill=(255, 60, 190, 180), width=3)
        draw.line([(64, 204), (385, 204)], fill=(255, 207, 72, 155), width=2)

    def _draw_metric_rows(self, canvas: Image.Image, data: GtavCardData, *, start_y: int) -> int:
        rows = [
            ("icon_moneybag.png", data.cash_label.upper(), _GREEN),
            ("icon_car_deluxo.png", data.cars_label.upper(), _PURPLE),
            ("icon_rp_badge.png", data.rank_label.upper(), _CYAN),
            ("icon_star.png", f"PLATFORM: {data.platform}".upper(), _GOLD),
        ]

        y = start_y
        for icon_name, text, accent in rows:
            self._draw_metric_row(canvas, icon_name, text, accent, y)
            y += 104
        return y

    def _draw_metric_row(
        self,
        canvas: Image.Image,
        icon_name: str,
        text: str,
        accent: tuple[int, int, int, int],
        y: int,
    ) -> None:
        x = 62
        w = 650
        h = 84
        radius = 15

        glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.rounded_rectangle(
            [x - 8, y - 8, x + w + 8, y + h + 8],
            radius=radius + 8,
            fill=(*accent[:3], 36),
        )
        canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(12)))

        row = _vertical_gradient((w, h), (23, 27, 42, 205), (8, 10, 22, 150), radius=radius)
        row_draw = ImageDraw.Draw(row)
        row_draw.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, outline=(*accent[:3], 115), width=1)
        row_draw.rectangle([0, 0, 6, h], fill=(*accent[:3], 185))

        chip_size = 64
        chip_x = 20
        chip_y = (h - chip_size) // 2
        row_draw.ellipse(
            [chip_x, chip_y, chip_x + chip_size, chip_y + chip_size],
            fill=(255, 255, 255, 22),
            outline=(*accent[:3], 115),
            width=1,
        )

        icon = self._load_icon(icon_name, size=54)
        if icon is not None:
            row.paste(icon, (chip_x + (chip_size - icon.width) // 2, chip_y + (chip_size - icon.height) // 2), icon)
        else:
            # No icon available — draw accent-colored circle as placeholder
            row_draw.ellipse(
                [chip_x + 4, chip_y + 4, chip_x + chip_size - 4, chip_y + chip_size - 4],
                fill=(*accent[:3], 72),
            )

        font = _fit_font(row_draw, text, 485, start_size=43, min_size=26, bold=True)
        text_w, text_h = _text_size(row_draw, text, font)
        y_offset = row_draw.textbbox((0, 0), text, font=font)[1]
        text_x = 105 + (500 - text_w) / 2
        text_y = (h - text_h) / 2 - y_offset
        _draw_glow_text(
            row,
            (text_x, text_y),
            text,
            font,
            fill=_GOLD_SOFT,
            stroke_width=2,
            stroke_fill=_BLACK,
            glow_fill=(*accent[:3], 42),
            glow_blur=6,
        )

        canvas.paste(row, (x, y), row)

    def _draw_tags(self, canvas: Image.Image, tags: tuple[str, ...], *, start_y: int) -> int:
        if not tags:
            return start_y

        draw = ImageDraw.Draw(canvas)
        heading_font = _font(31, bold=True)
        _draw_glow_text(
            canvas,
            (64, start_y),
            "EXTRA FEATURES",
            heading_font,
            fill=_WHITE,
            stroke_width=2,
            stroke_fill=_BLACK,
            glow_fill=(255, 60, 190, 60),
            glow_blur=7,
        )

        y = start_y + 54
        x = 64
        col_w = 300
        tag_font = _font(25, bold=True)
        for index, tag in enumerate(tags[:6]):
            col = index % 2
            row = index // 2
            tag_x = x + col * col_w
            tag_y = y + row * 48
            self._draw_tag(canvas, tag_x, tag_y, tag, tag_font)

        return y + ((min(len(tags), 6) + 1) // 2) * 48

    def _draw_tag(self, canvas: Image.Image, x: int, y: int, text: str, font: ImageFont.ImageFont) -> None:
        draw = ImageDraw.Draw(canvas)
        clean = text.strip().upper()
        max_w = 248
        font = _fit_font(draw, clean, max_w - 52, start_size=25, min_size=18, bold=True)
        tag_w = min(max_w, _text_size(draw, clean, font)[0] + 58)

        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.rounded_rectangle(
            [x, y, x + tag_w, y + 36],
            radius=10,
            fill=(9, 13, 26, 176),
            outline=(255, 207, 72, 90),
            width=1,
        )
        cx, cy = x + 20, y + 18
        d.polygon([(cx, cy - 7), (cx + 7, cy), (cx, cy + 7), (cx - 7, cy)], fill=_GOLD)
        d.text((x + 36, y + 6), clean, font=font, fill=_WHITE, stroke_width=1, stroke_fill=_BLACK)
        canvas.alpha_composite(layer)

    def _draw_delivery(self, canvas: Image.Image, delivery_text: str, *, start_y: int) -> None:
        text = (delivery_text or "INSTANT DELIVERY").upper()
        draw = ImageDraw.Draw(canvas)
        font = _fit_font(draw, text, 480, start_size=42, min_size=28, bold=True)
        text_w, text_h = _text_size(draw, text, font)
        badge_w = min(610, max(455, text_w + 112))
        badge_h = 82
        x = 62
        y = min(start_y, _H - badge_h - 48)

        glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.rounded_rectangle(
            [x - 12, y - 12, x + badge_w + 12, y + badge_h + 12],
            radius=22,
            fill=(255, 207, 72, 64),
        )
        canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(16)))

        badge = _vertical_gradient((badge_w, badge_h), (50, 35, 10, 238), (12, 11, 7, 226), radius=18)
        badge_draw = ImageDraw.Draw(badge)
        badge_draw.rounded_rectangle([1, 1, badge_w - 2, badge_h - 2], radius=18, outline=_GOLD, width=4)
        badge_draw.rounded_rectangle([9, 9, badge_w - 10, badge_h - 10], radius=12, outline=(255, 255, 255, 35), width=1)

        text_y_offset = badge_draw.textbbox((0, 0), text, font=font)[1]
        tx = (badge_w - text_w) / 2
        ty = (badge_h - text_h) / 2 - text_y_offset
        _draw_glow_text(
            badge,
            (tx, ty),
            text,
            font,
            fill=_GOLD_SOFT,
            stroke_width=2,
            stroke_fill=_BLACK,
            glow_fill=(255, 207, 72, 72),
            glow_blur=6,
        )
        canvas.paste(badge, (x, y), badge)

    def _load_icon(self, file_name: str, *, size: int) -> Image.Image | None:
        """Load icon from media directory. Returns None if not found."""
        key = (file_name, size)
        if key in self._icon_cache:
            return self._icon_cache[key].copy()

        path = _MEDIA_DIR / file_name
        if not path.is_file():
            return None

        icon = Image.open(path).convert("RGBA")
        icon = _remove_light_background(icon)
        bbox = icon.getbbox()
        if bbox:
            icon = icon.crop(bbox)
        icon.thumbnail((size, size), Image.LANCZOS)

        self._icon_cache[key] = icon.copy()
        return icon


def _normalize_tags(account: GtavResolvedAccount) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for raw in account.tags:
        tag = str(raw).strip()
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        tags.append(tag)

    if account.has_dual_characters and "dual characters" not in seen:
        tags.append("Dual Characters")

    return tags[:6]


def _crop_and_resize(image: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    target_w, target_h = target_size
    src_w, src_h = image.size
    src_ratio = src_w / src_h
    target_ratio = target_w / target_h

    if src_ratio > target_ratio:
        new_w = int(src_h * target_ratio)
        left = (src_w - new_w) // 2
        image = image.crop((left, 0, left + new_w, src_h))
    else:
        new_h = int(src_w / target_ratio)
        top = (src_h - new_h) // 2
        image = image.crop((0, top, src_w, top + new_h))

    return image.resize(target_size, Image.LANCZOS)


def _remove_light_background(image: Image.Image) -> Image.Image:
    """Remove checkerboard-style light backgrounds from bundled PNG icons."""
    pixels = []
    pixel_source = (
        image.get_flattened_data()
        if hasattr(image, "get_flattened_data")
        else image.getdata()
    )
    for r, g, b, a in pixel_source:
        is_light_gray = r > 205 and g > 205 and b > 205 and (max(r, g, b) - min(r, g, b)) < 24
        pixels.append((r, g, b, 0 if is_light_gray else a))
    image.putdata(pixels)
    return image


def _vertical_gradient(
    size: tuple[int, int],
    top_color: tuple[int, int, int, int],
    bottom_color: tuple[int, int, int, int],
    *,
    radius: int,
) -> Image.Image:
    w, h = size
    gradient = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(gradient)
    for y in range(h):
        t = y / max(h - 1, 1)
        color = tuple(int(top_color[i] + (bottom_color[i] - top_color[i]) * t) for i in range(4))
        draw.line([(0, y), (w, y)], fill=color)

    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    result = Image.new("RGBA", size, (0, 0, 0, 0))
    result.paste(gradient, (0, 0), mask)
    return result


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        [
            "C:/Windows/Fonts/arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "arialbd.ttf",
        ]
        if bold
        else [
            "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "arial.ttf",
        ]
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    *,
    start_size: int,
    min_size: int,
    bold: bool,
) -> ImageFont.ImageFont:
    for size in range(start_size, min_size - 1, -2):
        font = _font(size, bold=bold)
        if _text_size(draw, text, font)[0] <= max_width:
            return font
    return _font(min_size, bold=bold)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _draw_glow_text(
    canvas: Image.Image,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    *,
    fill: tuple[int, int, int, int],
    stroke_width: int = 0,
    stroke_fill: tuple[int, int, int, int] | None = None,
    glow_fill: tuple[int, int, int, int] | None = None,
    glow_blur: int = 8,
) -> None:
    if glow_fill:
        glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.text(
            xy,
            text,
            font=font,
            fill=glow_fill,
            stroke_width=stroke_width,
            stroke_fill=glow_fill,
        )
        canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(glow_blur)))

    draw = ImageDraw.Draw(canvas)
    draw.text(
        xy,
        text,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )
