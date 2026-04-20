"""LoL champion and skin title catalog backed by a bundled LolAllData.json.

Slice-local lookup — not intended for reuse outside the LoL account slice.
Lazy-loaded on first access, then cached for the process lifetime.

The default data file lives under ``resources/LolAllData.json`` next to this
module.  Callers that need a different file can call ``configure(path)``
before the first lookup.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_RESOURCES_DIR = Path(__file__).resolve().parent / "resources"
_DEFAULT_ASSETS_PATH = _RESOURCES_DIR / "LolAllData.json"

_assets_path: Path = _DEFAULT_ASSETS_PATH
_champion_map: dict[int, str] | None = None
_skin_map: dict[int, str] | None = None


def configure(path: str | Path) -> None:
    """Override the catalog data file before first use.

    Raises ``RuntimeError`` if the catalog has already been loaded.
    """
    global _assets_path, _champion_map, _skin_map
    if _champion_map is not None:
        raise RuntimeError("LoL catalog already loaded — configure() must be called before first lookup")
    _assets_path = Path(path)


def _load() -> tuple[dict[int, str], dict[int, str]]:
    global _champion_map, _skin_map
    if _champion_map is not None and _skin_map is not None:
        return _champion_map, _skin_map

    data: dict[str, Any] = json.loads(_assets_path.read_text(encoding="utf-8"))

    _champion_map = {}
    for entry in data.get("Champions", []):
        cid = _safe_int(entry.get("id"))
        title = entry.get("title", "")
        if cid is not None and title:
            _champion_map[cid] = title

    _skin_map = {}
    for entry in data.get("Skins", []):
        sid = _safe_int(entry.get("id"))
        title = entry.get("title", "")
        if sid is not None and title:
            _skin_map[sid] = title

    return _champion_map, _skin_map


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def champion_title(champion_id: int) -> str | None:
    """Return champion title for the given ID, or None if unknown."""
    champions, _ = _load()
    return champions.get(champion_id)


def skin_title(skin_id: int) -> str | None:
    """Return skin title for the given ID, or None if unknown."""
    _, skins = _load()
    return skins.get(skin_id)


def champion_titles(champion_ids: list[int]) -> list[str]:
    """Resolve a list of champion IDs to their titles, skipping unknowns."""
    champions, _ = _load()
    return [champions[cid] for cid in champion_ids if cid in champions]


def skin_titles(skin_ids: list[int]) -> list[str]:
    """Resolve a list of skin IDs to their titles, skipping unknowns and defaults."""
    _, skins = _load()
    result = []
    for sid in skin_ids:
        title = skins.get(sid)
        if title and title != "default":
            result.append(title)
    return result
