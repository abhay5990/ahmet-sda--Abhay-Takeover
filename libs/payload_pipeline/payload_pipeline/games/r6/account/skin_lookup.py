"""Self-contained skin lookup for the R6 account slice.

Uses slice-local resources/RainbowSkins.json — no src.games dependency.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


_RESOURCES_DIR = Path(__file__).resolve().parent / "resources"
_SKINS_JSON = _RESOURCES_DIR / "RainbowSkins.json"


@lru_cache(maxsize=1)
def _load_skins_by_id() -> dict[str, dict[str, Any]]:
    """Load and index RainbowSkins.json by data_id, once per process."""
    for candidate in (_SKINS_JSON, Path("assets/r6/RainbowSkins.json"), Path("assets/rainbow/RainbowSkins.json")):
        if candidate.exists():
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(raw, list):
                by_id: dict[str, dict[str, Any]] = {}
                for entry in raw:
                    if not isinstance(entry, dict):
                        continue
                    key = str(entry.get("data_id") or "").strip()
                    if key and key not in by_id:
                        by_id[key] = entry
                return by_id
    return {}


def count_black_ice(skin_ids: list[str]) -> int:
    """Count Black Ice skins from LZT skin IDs."""
    if not skin_ids:
        return 0

    skins_by_id = _load_skins_by_id()
    count = 0
    for skin_id in skin_ids:
        info = skins_by_id.get(str(skin_id or "").strip())
        if info and "BLACK ICE" in str(info.get("alt") or "").upper():
            count += 1
    return count


def resolve_skin_names(skin_ids: list[str]) -> list[str]:
    """Resolve skin titles from LZT skin IDs."""
    if not skin_ids:
        return []

    skins_by_id = _load_skins_by_id()
    titles: list[str] = []
    for skin_id in skin_ids:
        info = skins_by_id.get(str(skin_id or "").strip())
        if info:
            title = str(info.get("alt") or "").strip()
            if title:
                titles.append(title)
    return titles


def resolve_skin_name_map(skin_ids: list[str]) -> dict[str, str]:
    """Resolve LZT skin IDs into a stable id->title mapping."""
    if not skin_ids:
        return {}

    skins_by_id = _load_skins_by_id()
    resolved: dict[str, str] = {}
    for skin_id in skin_ids:
        key = str(skin_id or "").strip()
        if not key:
            continue
        info = skins_by_id.get(key)
        if info:
            title = str(info.get("alt") or "").strip()
            if title:
                resolved[key] = title
    return resolved
