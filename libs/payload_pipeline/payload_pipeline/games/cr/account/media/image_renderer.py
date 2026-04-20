"""Clash Royale card grid image renderer.

Generates a grid image of card icons sorted by rarity with level
overlays — matching the output of the legacy
``src/games/games/cr/generators/image_generator.py``.
"""

from __future__ import annotations

import json
import logging
import math
import os
from io import BytesIO
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
_GRID_COLS = 10
_CARD_WIDTH = 80
_CARD_HEIGHT = 100
_BG_COLOR = (53, 82, 151, 255)  # Mat mavi

_RARITY_ORDER = {
    "Common": 5,
    "Rare": 4,
    "Epic": 3,
    "Legendary": 2,
    "Champion": 1,
}


class CrImageRenderer:
    """Render a card grid image from resolved Clash Royale data."""

    def __init__(
        self,
        spells_path: str | Path | None = None,
        cache_dir: str | None = None,
    ) -> None:
        self._spells_path = Path(spells_path) if spells_path else _DEFAULT_SPELLS_PATH
        self._cache_dir = Path(
            cache_dir or os.path.join(default_cache_base_dir("clash-royale"), "cards")
        )
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        self._session = requests.Session()
        self._session.mount("https://", HTTPAdapter(pool_connections=5, pool_maxsize=10))
        self._session.mount("http://", HTTPAdapter(pool_connections=2, pool_maxsize=5))

        self._spells_data: dict[str, dict] | None = None

    @property
    def spells_data(self) -> dict[str, dict]:
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
            logger.warning("No cards data — skipping image generation.")
            return None

        cards = self._prepare_cards(cards_data)
        if not cards:
            return None

        total = len(cards)
        rows = math.ceil(total / _GRID_COLS)
        grid_w = _GRID_COLS * _CARD_WIDTH
        grid_h = rows * _CARD_HEIGHT

        grid = Image.new("RGBA", (grid_w, grid_h), _BG_COLOR)

        for i, card in enumerate(cards):
            row, col = divmod(i, _GRID_COLS)
            card_img = self._download_card(card["id"])
            card_img = card_img.resize((_CARD_WIDTH, _CARD_HEIGHT))
            card_img = self._add_background(card_img)
            card_img = self._add_level_overlay(card_img, card)
            grid.paste(card_img, (col * _CARD_WIDTH, row * _CARD_HEIGHT))

        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            grid.save(output_path)
            logger.info("CR card grid saved: %s", output_path)
            return output_path
        except Exception as exc:
            logger.error("Failed to save card grid: %s", exc)
            return None

    # ── data helpers ──────────────────────────────────────────────────

    def _load_spells(self) -> dict[str, dict]:
        try:
            with open(self._spells_path, "r", encoding="utf-8") as f:
                spells_list = json.load(f)
            return {
                str(s["id"]): {"name": s.get("name", "Unknown"), "rarity": s.get("rarity", "Common")}
                for s in spells_list
                if "id" in s
            }
        except Exception as exc:
            logger.error("Failed to load spells data: %s", exc)
            return {}

    def _prepare_cards(self, cards_dict: dict[str, dict[str, Any]]) -> list[dict]:
        cards: list[dict] = []
        for card_id, card_info in cards_dict.items():
            spell = self.spells_data.get(str(card_id), {})
            rarity = spell.get("rarity", "Common")
            cards.append({
                "id": card_id,
                "name": card_info.get("name", spell.get("name", "Unknown")),
                "normalizedLevel": card_info.get("normalizedLevel", 1),
                "rarity": rarity,
                "rarity_order": _RARITY_ORDER.get(rarity, 1),
            })
        cards.sort(key=lambda c: (c["rarity_order"], c["name"]))
        return cards

    # ── image helpers ─────────────────────────────────────────────────

    def _download_card(self, card_id: str) -> Image.Image:
        cache_file = self._cache_dir / f"{card_id}.png"

        if cache_file.exists():
            try:
                return Image.open(cache_file).convert("RGBA")
            except Exception:
                cache_file.unlink(missing_ok=True)

        try:
            url = f"{_BASE_URL}{card_id}.png"
            resp = self._session.get(url, timeout=10)
            resp.raise_for_status()
            img = Image.open(BytesIO(resp.content)).convert("RGBA")
            try:
                img.save(cache_file, "PNG")
            except Exception:
                pass
            return img
        except Exception:
            return Image.new("RGBA", (100, 120), (200, 200, 200, 255))

    @staticmethod
    def _add_background(card_img: Image.Image) -> Image.Image:
        bg = Image.new("RGBA", card_img.size, _BG_COLOR)
        bg.paste(card_img, (0, 0), card_img)
        return bg

    @staticmethod
    def _add_level_overlay(card_img: Image.Image, card: dict) -> Image.Image:
        img = card_img.copy()
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 14)
        except IOError:
            font = ImageFont.load_default()

        w, h = img.size
        text = f"Level {card['normalizedLevel']}"
        tw = draw.textlength(text, font=font)
        draw.text(
            ((w - tw) // 2, h - 25), text, fill=(255, 255, 255, 255), font=font
        )
        return img
