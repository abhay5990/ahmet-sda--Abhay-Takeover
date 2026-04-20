"""League of Legends champion/skin grid image renderer.

Generates grid images of champion icons and skin splashes — matching
the output of the legacy ``src/games/games/lol/generators/image_generator.py``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps
from requests.adapters import HTTPAdapter

from .....shared.paths import default_cache_base_dir

logger = logging.getLogger(__name__)

_RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
_DEFAULT_DATA_PATH = _RESOURCES_DIR / "LolAllData.json"

# Grid layout constants (match legacy generator)
_CHAMPION_COLUMNS = 8
_SKIN_COLUMNS = 5
_CHAMPION_HEIGHT = 100
_SKIN_HEIGHT = 79
_PANEL_HEIGHT = 24
_FONT_SIZE = 15
_BORDER_COLOR = "gray"
_BORDER_THICKNESS = 3
_BG_COLOR = (169, 169, 169)


class LolImageRenderer:
    """Render champion and skin grid images from resolved LoL data."""

    def __init__(
        self,
        data_path: str | Path | None = None,
        cache_dir: str | None = None,
    ) -> None:
        self._data_path = Path(data_path) if data_path else _DEFAULT_DATA_PATH
        self._cache_dir = cache_dir or os.path.join(
            default_cache_base_dir("league-of-legends"), "images"
        )
        os.makedirs(os.path.join(self._cache_dir, "champions"), exist_ok=True)
        os.makedirs(os.path.join(self._cache_dir, "skins"), exist_ok=True)

        self._session = requests.Session()
        self._session.mount("https://", HTTPAdapter(pool_connections=5, pool_maxsize=10))
        self._session.mount("http://", HTTPAdapter(pool_connections=2, pool_maxsize=5))

        self._lol_data: dict | None = None

    @property
    def lol_data(self) -> dict:
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
        """Build champion and skin grids, return list of saved file paths."""
        saved: list[str] = []
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        for item_type, ids, columns, target_h in [
            ("Champions", champion_ids, _CHAMPION_COLUMNS, _CHAMPION_HEIGHT),
            ("Skins", skin_ids, _SKIN_COLUMNS, _SKIN_HEIGHT),
        ]:
            if not ids:
                continue

            file_name = f"{item_type}.{item_id}.png"
            save_path = os.path.join(output_dir, file_name)

            data_source = self.lol_data.get(item_type, [])
            images = self._build_item_images(ids, item_type, data_source, target_h)
            if not images:
                logger.warning("No images found for %s", item_type)
                continue

            combined = self._combine_grid(images, columns, str(len(images)))
            if combined is None:
                continue

            try:
                # Match legacy: cv2.imwrite via numpy (RGB→BGR→file)
                import cv2
                combined_np = np.array(combined)
                cv2.imwrite(save_path, cv2.cvtColor(combined_np, cv2.COLOR_RGB2BGR))
                logger.info("%s grid saved: %s", item_type, save_path)
                saved.append(save_path)
            except Exception as exc:
                logger.error("Failed to save %s grid: %s", item_type, exc)

        return saved

    # ── private helpers ───────────────────────────────────────────────

    def _load_data(self) -> dict:
        try:
            with open(self._data_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.error("Failed to load LoL data from %s: %s", self._data_path, exc)
            return {"Champions": [], "Skins": []}

    def _build_item_images(
        self,
        ids: list[int],
        item_type: str,
        data_source: list[dict],
        target_height: int,
    ) -> list[Image.Image]:
        images: list[Image.Image] = []
        for item_id in ids:
            entry = next(
                (e for e in data_source if str(e.get("id")) == str(item_id)), None
            )
            if not entry:
                continue

            img_np = self._get_cached_image(str(item_id), item_type, entry["src"])
            if img_np is None:
                continue

            img_np = self._resize(img_np, target_height)
            img_pil = self._add_title(img_np, entry.get("title", "No Title"))
            img_pil = ImageOps.expand(img_pil, border=_BORDER_THICKNESS, fill=_BORDER_COLOR)
            images.append(img_pil)
        return images

    def _get_cached_image(
        self, item_id: str, item_type: str, url: str
    ) -> np.ndarray | None:
        subdir = "champions" if item_type == "Champions" else "skins"
        cache_path = os.path.join(self._cache_dir, subdir, f"{item_id}.png")

        if os.path.exists(cache_path):
            return self._load_np(cache_path)

        if self._download(url, cache_path):
            return self._load_np(cache_path)
        return None

    def _download(self, url: str, cache_path: str) -> bool:
        try:
            resp = self._session.get(url, timeout=10)
            resp.raise_for_status()
            with open(cache_path, "wb") as f:
                f.write(resp.content)
            return True
        except Exception as exc:
            logger.warning("Image download failed %s: %s", url, exc)
            return False

    @staticmethod
    def _load_np(path: str) -> np.ndarray | None:
        try:
            return np.array(Image.open(path))
        except Exception:
            return None

    @staticmethod
    def _resize(img_np: np.ndarray, target_height: int) -> np.ndarray:
        img = Image.fromarray(img_np)
        aspect = img.width / img.height
        new_w = int(aspect * target_height)
        return np.array(img.resize((new_w, target_height), Image.Resampling.LANCZOS))

    @staticmethod
    def _add_title(
        img_np: np.ndarray,
        title: str,
        panel_height: int = _PANEL_HEIGHT,
        font_size: int = _FONT_SIZE,
    ) -> Image.Image:
        img = Image.fromarray(img_np)
        draw = ImageDraw.Draw(img)
        w, h = img.size

        panel = Image.new("RGBA", (w, panel_height), (0, 0, 0, 128))
        img.paste(panel, (0, h - panel_height), panel)

        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except IOError:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), title, font=font)
        tw = bbox[2] - bbox[0]

        while tw > w and font_size > 1:
            font_size -= 1
            try:
                font = ImageFont.truetype("arial.ttf", font_size)
            except IOError:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), title, font=font)
            tw = bbox[2] - bbox[0]

        th = bbox[3] - bbox[1]
        pos = ((w - tw) // 2, h - panel_height + (panel_height - th) // 2)
        draw.text(pos, title, fill=(255, 255, 255, 255), font=font)
        return img

    @staticmethod
    def _combine_grid(
        images: list[Image.Image], columns: int, count_text: str
    ) -> Image.Image | None:
        if not images:
            return None

        rows = (len(images) + columns - 1) // columns
        max_w = max(img.width for img in images)
        max_h = max(img.height for img in images)

        grid_w = columns * max_w + 8
        grid_h = rows * max_h + 42

        combined = Image.new("RGB", (grid_w, grid_h), _BG_COLOR)
        draw = ImageDraw.Draw(combined)

        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except IOError:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), count_text, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((grid_w - tw) // 2, 10), count_text, fill=(255, 255, 255), font=font)

        y = 40
        for i, img in enumerate(images):
            x = (i % columns) * max_w + 4
            combined.paste(img, (x, y))
            if (i + 1) % columns == 0:
                y += max_h

        return combined
