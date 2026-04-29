"""Clash of Clans account image renderer.

Generates 4 PNG images from resolved account data:
1. heroes_equipment.png - Heroes + Equipment (grouped by hero)
2. troops.png - Home Village Troops (elixir + dark)
3. spells_supers.png - Spells + Super Troops
4. builder_base.png - Builder Base (optional)
"""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .....shared.paths import default_cache_base_dir

_RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
_DEFAULT_IMAGE_MAP_DIR = _RESOURCES_DIR / "image_map"

# Hero ID -> name mapping
_HERO_NAMES = {
    0: "Barbarian King",
    1: "Archer Queen",
    2: "Grand Warden",
    3: "Battle Machine",
    4: "Royal Champion",
    5: "Battle Copter",
    6: "Minion Prince",
}

HOME_HEROES = [0, 1, 2, 4, 6]
BUILDER_HEROES = [3, 5]


class CocImageRenderer:
    """Render Clash of Clans account images from resolved data arrays."""

    def __init__(self, cache_folder: str | None = None) -> None:
        default_icon_cache = Path(default_cache_base_dir("clash-of-clans")) / "icons"
        self.cache_folder = Path(cache_folder) if cache_folder else default_icon_cache
        self.cache_roots = [self.cache_folder, _DEFAULT_IMAGE_MAP_DIR]
        if cache_folder:
            self.cache_roots.append(default_icon_cache)
        default_icon_cache.mkdir(parents=True, exist_ok=True)

        self.colors = {
            "bg_dark": (30, 30, 35, 255),
            "bg_section": (45, 45, 50, 255),
            "bg_header": (60, 60, 70, 255),
            "text_white": (255, 255, 255, 255),
            "text_gray": (180, 180, 180, 255),
            "text_gold": (255, 215, 0, 255),
            "text_green": (100, 255, 100, 255),
            "level_bg": (0, 0, 0, 180),
            "owned_border": (100, 200, 100, 255),
            "locked_border": (80, 80, 80, 255),
            "active_glow": (255, 215, 0, 100),
        }

        self.icon_size = (64, 64)
        self.hero_icon_size = (80, 80)
        self.padding = 8
        self.section_padding = 15
        self.canvas_width = 620
        self.grid_cols = (self.canvas_width - self.section_padding * 2) // (
            self.icon_size[0] + self.padding
        )

        self.fonts = self._load_fonts()

    def render(
        self,
        heroes: list[dict[str, Any]],
        troops: list[dict[str, Any]],
        spells: list[dict[str, Any]],
        hero_equipment: list[dict[str, Any]],
        super_troops: list[dict[str, Any]],
        player_tag: str,
        output_dir: str,
    ) -> list[str]:
        """Generate all CoC images and return list of created file paths."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        tag = player_tag.replace("#", "") if player_tag else "UNKNOWN"
        created: list[str] = []

        account_data = {
            "heroes": heroes,
            "troops": troops,
            "spells": spells,
            "heroEquipment": hero_equipment,
            "superTroops": super_troops,
        }

        path = os.path.join(output_dir, f"{tag}_heroes_equipment.png")
        result = self._create_heroes_equipment_image(account_data, path)
        if result:
            created.append(result)

        path = os.path.join(output_dir, f"{tag}_troops.png")
        result = self._create_troops_image(account_data, path)
        if result:
            created.append(result)

        path = os.path.join(output_dir, f"{tag}_spells_supers.png")
        result = self._create_spells_supers_image(account_data, path)
        if result:
            created.append(result)

        path = os.path.join(output_dir, f"{tag}_builder_base.png")
        result = self._create_builder_base_image(account_data, path)
        if result:
            created.append(result)

        return created

    # ------------------------------------------------------------------
    # Font loading
    # ------------------------------------------------------------------

    def _load_fonts(self) -> dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
        fonts: dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "arial.ttf",
            "Arial.ttf",
        ]

        for size_name, size in [
            ("small", 11),
            ("medium", 14),
            ("large", 18),
            ("title", 22),
        ]:
            font = None
            for path in font_paths:
                try:
                    font = ImageFont.truetype(path, size)
                    break
                except Exception:
                    continue
            if font is None:
                font = ImageFont.load_default()
            fonts[size_name] = font

        return fonts

    # ------------------------------------------------------------------
    # Icon loading + helpers
    # ------------------------------------------------------------------

    def _load_icon(
        self, category: str, item_id: int, owned: bool = True
    ) -> Image.Image | None:
        for root in self.cache_roots:
            for filepath in self._candidate_icon_paths(root, category, item_id):
                if not filepath.exists():
                    continue

                try:
                    img = Image.open(filepath).convert("RGBA")
                    if category == "hero":
                        img = img.resize(self.hero_icon_size, Image.Resampling.LANCZOS)
                    else:
                        img = img.resize(self.icon_size, Image.Resampling.LANCZOS)
                    if not owned:
                        img = self._make_grayscale(img)
                    return img
                except Exception:
                    continue

        return self._create_placeholder(category, item_id, owned)

    @staticmethod
    def _candidate_icon_paths(root: Path, category: str, item_id: int) -> list[Path]:
        return [
            root / category / f"{category}-{item_id}.png",
            root / category / f"{item_id}.png",
            root / f"{category}-{item_id}.png",
            root / f"{item_id}.png",
        ]

    def _create_placeholder(
        self, category: str, item_id: int, owned: bool
    ) -> Image.Image:
        size = self.hero_icon_size if category == "hero" else self.icon_size
        color = (100, 100, 120, 255) if owned else (60, 60, 70, 255)

        img = Image.new("RGBA", size, color)
        draw = ImageDraw.Draw(img)

        text = str(item_id)
        bbox = draw.textbbox((0, 0), text, font=self.fonts["small"])
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (size[0] - text_width) // 2
        y = (size[1] - text_height) // 2
        draw.text(
            (x, y), text, fill=(150, 150, 150, 255), font=self.fonts["small"]
        )

        return img

    def _make_grayscale(
        self, img: Image.Image, alpha_factor: float = 0.5
    ) -> Image.Image:
        gray = img.convert("LA").convert("RGBA")
        r, g, b, a = gray.split()
        a = a.point(lambda x: int(x * alpha_factor))
        gray.putalpha(a)
        return gray

    def _add_level_badge(
        self, img: Image.Image, level: int, max_level: int | None = None
    ) -> Image.Image:
        img_copy = img.copy()
        draw = ImageDraw.Draw(img_copy)
        width, height = img_copy.size

        if level > 0:
            text = str(level)
            text_color = (
                self.colors["text_gold"]
                if max_level and level >= max_level
                else self.colors["text_white"]
            )
        else:
            text = "-"
            text_color = self.colors["text_gray"]

        badge_height = 16
        badge_y = height - badge_height

        overlay = Image.new("RGBA", img_copy.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rectangle(
            [(0, badge_y), (width, height)], fill=(0, 0, 0, 180)
        )
        img_copy = Image.alpha_composite(img_copy, overlay)

        draw = ImageDraw.Draw(img_copy)
        bbox = draw.textbbox((0, 0), text, font=self.fonts["small"])
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        y = badge_y + 1
        draw.text((x, y), text, fill=text_color, font=self.fonts["small"])

        return img_copy

    def _add_active_indicator(self, img: Image.Image) -> Image.Image:
        img_copy = img.copy()
        draw = ImageDraw.Draw(img_copy)
        width, height = img_copy.size
        border_width = 2
        draw.rectangle(
            [(0, 0), (width - 1, height - 1)],
            outline=(100, 255, 100, 255),
            width=border_width,
        )
        return img_copy

    def _add_date_watermark(
        self, canvas: Image.Image, date_str: str | None = None
    ) -> Image.Image:
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        draw = ImageDraw.Draw(canvas)
        width, _ = canvas.size

        text = date_str
        bbox = draw.textbbox((0, 0), text, font=self.fonts["small"])
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        padding_x = 8
        padding_y = 4

        badge_width = text_width + padding_x * 2
        badge_height = text_height + padding_y * 2
        badge_x = width - badge_width - 8
        badge_y = 8

        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rounded_rectangle(
            [(badge_x, badge_y), (badge_x + badge_width, badge_y + badge_height)],
            radius=4,
            fill=(0, 0, 0, 160),
        )
        canvas = Image.alpha_composite(canvas, overlay)

        draw = ImageDraw.Draw(canvas)
        text_x = badge_x + padding_x
        text_y = badge_y + padding_y
        draw.text(
            (text_x, text_y),
            text,
            fill=self.colors["text_gray"],
            font=self.fonts["small"],
        )

        return canvas

    def _draw_section_header(
        self, draw: ImageDraw.Draw, text: str, y: int, width: int
    ) -> int:
        header_height = 30
        draw.rectangle(
            [(0, y), (width, y + header_height)], fill=self.colors["bg_header"]
        )
        draw.text(
            (self.section_padding, y + 5),
            text,
            fill=self.colors["text_gold"],
            font=self.fonts["large"],
        )
        return y + header_height + 5

    # ------------------------------------------------------------------
    # Image 1: Heroes & Equipment
    # ------------------------------------------------------------------

    def _create_heroes_equipment_image(
        self, account_data: dict[str, Any], output_path: str
    ) -> str | None:
        heroes = account_data.get("heroes", [])
        equipment = account_data.get("heroEquipment", [])

        if not heroes:
            return None

        equipment_by_hero: dict[int, list[dict[str, Any]]] = {}
        for eq in equipment:
            hero_id = eq.get("hero", 0)
            if hero_id not in equipment_by_hero:
                equipment_by_hero[hero_id] = []
            equipment_by_hero[hero_id].append(eq)

        home_heroes = [h for h in heroes if h.get("village") == "home"]
        home_heroes.sort(key=lambda x: x.get("order", x["id"]))

        row_height = self.hero_icon_size[1] + self.padding
        canvas_width = self.canvas_width
        canvas_height = (
            40 + (len(home_heroes) * (row_height + 10)) + self.section_padding * 2
        )

        canvas = Image.new("RGBA", (canvas_width, canvas_height), self.colors["bg_dark"])
        draw = ImageDraw.Draw(canvas)

        y = self._draw_section_header(draw, "\U0001f981 HEROES & EQUIPMENT", 0, canvas_width)
        y += 5

        for hero in home_heroes:
            hero_id = hero["id"]
            hero_name = _HERO_NAMES.get(hero_id, f"Hero {hero_id}")
            hero_level = hero.get("level", 0)
            hero_owned = hero_level > 0

            x = self.section_padding

            hero_icon = self._load_icon("hero", hero_id, hero_owned)
            if hero_icon:
                hero_icon = self._add_level_badge(
                    hero_icon, hero_level, hero.get("maxLevel")
                )
                canvas.paste(hero_icon, (x, y), hero_icon)

            x += self.hero_icon_size[0] + self.padding * 2

            name_color = (
                self.colors["text_white"] if hero_owned else self.colors["text_gray"]
            )
            draw.text((x, y), hero_name, fill=name_color, font=self.fonts["medium"])

            eq_y = y + 20
            eq_x = x

            hero_equipment = equipment_by_hero.get(hero_id, [])
            hero_equipment.sort(key=lambda e: e.get("order", e["id"]))

            for eq in hero_equipment:
                eq_id = eq["id"]
                eq_level = eq.get("level", 0)
                eq_unlocked = eq.get("isUnlocked", False)
                eq_active = eq.get("isActive", False)

                eq_icon = self._load_icon("he", eq_id, eq_unlocked)
                if eq_icon:
                    eq_icon = self._add_level_badge(
                        eq_icon, eq_level, eq.get("maxLevel")
                    )
                    if eq_active and eq_unlocked:
                        eq_icon = self._add_active_indicator(eq_icon)
                    canvas.paste(eq_icon, (eq_x, eq_y), eq_icon)

                eq_x += self.icon_size[0] + self.padding

            y += row_height + 10

        canvas = self._add_date_watermark(canvas)
        canvas.save(output_path)
        return output_path

    # ------------------------------------------------------------------
    # Image 2: Troops
    # ------------------------------------------------------------------

    def _create_troops_image(
        self, account_data: dict[str, Any], output_path: str
    ) -> str | None:
        troops = account_data.get("troops", [])
        if not troops:
            return None

        home_troops = [t for t in troops if t.get("village") == "home"]
        elixir_troops = [t for t in home_troops if not t.get("isDark", False)]
        dark_troops = [t for t in home_troops if t.get("isDark", False)]

        elixir_troops.sort(key=lambda x: x.get("order", x["id"]))
        dark_troops.sort(key=lambda x: x.get("order", x["id"]))

        cols = self.grid_cols
        elixir_rows = (len(elixir_troops) + cols - 1) // cols
        dark_rows = (len(dark_troops) + cols - 1) // cols
        row_height = self.icon_size[1] + self.padding

        canvas_width = self.canvas_width
        canvas_height = (
            35 + elixir_rows * row_height + 35 + dark_rows * row_height
            + self.section_padding * 2
        )

        canvas = Image.new("RGBA", (canvas_width, canvas_height), self.colors["bg_dark"])
        draw = ImageDraw.Draw(canvas)

        y = self._draw_section_header(draw, "\u2694\ufe0f ELIXIR TROOPS", 0, canvas_width)
        y = self._draw_troop_grid(canvas, elixir_troops, y, cols)

        y = self._draw_section_header(draw, "\U0001f319 DARK TROOPS", y + 5, canvas_width)
        y = self._draw_troop_grid(canvas, dark_troops, y, cols)

        canvas = self._add_date_watermark(canvas)
        canvas.save(output_path)
        return output_path

    def _draw_troop_grid(
        self,
        canvas: Image.Image,
        troops: list[dict[str, Any]],
        start_y: int,
        cols: int,
    ) -> int:
        y = start_y
        for i, troop in enumerate(troops):
            row = i // cols
            col = i % cols
            x = self.section_padding + col * (self.icon_size[0] + self.padding)
            current_y = y + row * (self.icon_size[1] + self.padding)
            troop_id = troop["id"]
            level = troop.get("level", 0)
            owned = level > 0
            icon = self._load_icon("troop", troop_id, owned)
            if icon:
                icon = self._add_level_badge(icon, level, troop.get("maxLevel"))
                canvas.paste(icon, (x, current_y), icon)
        total_rows = (len(troops) + cols - 1) // cols
        return y + total_rows * (self.icon_size[1] + self.padding)

    # ------------------------------------------------------------------
    # Image 3: Spells & Super Troops
    # ------------------------------------------------------------------

    def _create_spells_supers_image(
        self, account_data: dict[str, Any], output_path: str
    ) -> str | None:
        spells = account_data.get("spells", [])
        super_troops = account_data.get("superTroops", [])

        if not spells and not super_troops:
            return None

        home_spells = [s for s in spells if s.get("village") == "home"]
        elixir_spells = [s for s in home_spells if not s.get("isDark", False)]
        dark_spells = [s for s in home_spells if s.get("isDark", False)]

        elixir_spells.sort(key=lambda x: x.get("order", x["id"]))
        dark_spells.sort(key=lambda x: x.get("order", x["id"]))
        super_troops.sort(key=lambda x: x.get("order", x["id"]))

        cols = self.grid_cols
        elixir_rows = (len(elixir_spells) + cols - 1) // cols if elixir_spells else 0
        dark_rows = (len(dark_spells) + cols - 1) // cols if dark_spells else 0
        super_rows = (len(super_troops) + cols - 1) // cols if super_troops else 0
        row_height = self.icon_size[1] + self.padding

        canvas_width = self.canvas_width
        canvas_height = (
            (35 + elixir_rows * row_height if elixir_spells else 0)
            + (35 + dark_rows * row_height if dark_spells else 0)
            + (35 + super_rows * row_height if super_troops else 0)
            + self.section_padding * 2
        )

        canvas = Image.new(
            "RGBA", (canvas_width, max(100, canvas_height)), self.colors["bg_dark"]
        )
        draw = ImageDraw.Draw(canvas)

        y = 0

        if elixir_spells:
            y = self._draw_section_header(
                draw, "\u2728 ELIXIR SPELLS", y, canvas_width
            )
            y = self._draw_spell_grid(canvas, elixir_spells, y, cols)

        if dark_spells:
            y = self._draw_section_header(
                draw, "\U0001f311 DARK SPELLS", y + 5, canvas_width
            )
            y = self._draw_spell_grid(canvas, dark_spells, y, cols)

        if super_troops:
            y = self._draw_section_header(
                draw, "\U0001f4aa SUPER TROOPS", y + 5, canvas_width
            )
            y = self._draw_super_troop_grid(canvas, super_troops, y, cols)

        canvas = self._add_date_watermark(canvas)
        canvas.save(output_path)
        return output_path

    def _draw_spell_grid(
        self,
        canvas: Image.Image,
        spells: list[dict[str, Any]],
        start_y: int,
        cols: int,
    ) -> int:
        y = start_y
        for i, spell in enumerate(spells):
            row = i // cols
            col = i % cols
            x = self.section_padding + col * (self.icon_size[0] + self.padding)
            current_y = y + row * (self.icon_size[1] + self.padding)
            spell_id = spell["id"]
            level = spell.get("level", 0)
            owned = level > 0
            icon = self._load_icon("spell", spell_id, owned)
            if icon:
                icon = self._add_level_badge(icon, level, spell.get("maxLevel"))
                canvas.paste(icon, (x, current_y), icon)
        total_rows = (len(spells) + cols - 1) // cols
        return y + total_rows * (self.icon_size[1] + self.padding)

    def _draw_super_troop_grid(
        self,
        canvas: Image.Image,
        super_troops: list[dict[str, Any]],
        start_y: int,
        cols: int,
    ) -> int:
        y = start_y
        for i, st in enumerate(super_troops):
            row = i // cols
            col = i % cols
            x = self.section_padding + col * (self.icon_size[0] + self.padding)
            current_y = y + row * (self.icon_size[1] + self.padding)
            st_id = st["id"]
            level = st.get("level", 0)
            unlocked = st.get("isUnlocked", False)
            active = st.get("isActive", False)
            icon = self._load_icon("super-troop", st_id, unlocked)
            if icon:
                icon = self._add_level_badge(icon, level, st.get("maxLevel"))
                if active and unlocked:
                    icon = self._add_active_indicator(icon)
                canvas.paste(icon, (x, current_y), icon)
        total_rows = (len(super_troops) + cols - 1) // cols
        return y + total_rows * (self.icon_size[1] + self.padding)

    # ------------------------------------------------------------------
    # Image 4: Builder Base
    # ------------------------------------------------------------------

    def _create_builder_base_image(
        self, account_data: dict[str, Any], output_path: str
    ) -> str | None:
        troops = account_data.get("troops", [])
        heroes = account_data.get("heroes", [])

        builder_troops = [t for t in troops if t.get("village") == "builder"]
        builder_heroes = [h for h in heroes if h.get("village") == "builder"]

        if not builder_troops and not builder_heroes:
            return None

        builder_troops.sort(key=lambda x: x.get("order", x["id"]))
        builder_heroes.sort(key=lambda x: x.get("order", x["id"]))

        cols = self.grid_cols
        troop_rows = (len(builder_troops) + cols - 1) // cols if builder_troops else 0
        row_height = self.icon_size[1] + self.padding
        hero_row_height = self.hero_icon_size[1] + self.padding

        canvas_width = self.canvas_width
        canvas_height = (
            (35 + hero_row_height if builder_heroes else 0)
            + (35 + troop_rows * row_height if builder_troops else 0)
            + self.section_padding * 2
        )

        canvas = Image.new(
            "RGBA", (canvas_width, max(100, canvas_height)), self.colors["bg_dark"]
        )
        draw = ImageDraw.Draw(canvas)

        y = 0

        if builder_heroes:
            y = self._draw_section_header(
                draw, "\U0001f528 BUILDER HEROES", y, canvas_width
            )
            x = self.section_padding

            for hero in builder_heroes:
                hero_id = hero["id"]
                level = hero.get("level", 0)
                owned = level > 0
                icon = self._load_icon("hero", hero_id, owned)
                if icon:
                    icon = self._add_level_badge(icon, level, hero.get("maxLevel"))
                    canvas.paste(icon, (x, y), icon)
                x += self.hero_icon_size[0] + self.padding
            y += hero_row_height

        if builder_troops:
            y = self._draw_section_header(
                draw, "\U0001f3d7\ufe0f BUILDER TROOPS", y + 5, canvas_width
            )
            y = self._draw_troop_grid(canvas, builder_troops, y, cols)

        canvas = self._add_date_watermark(canvas)
        canvas.save(output_path)
        return output_path
