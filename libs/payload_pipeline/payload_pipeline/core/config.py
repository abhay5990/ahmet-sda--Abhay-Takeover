"""Pipeline feature configuration loader.

Reads pipeline.config.json from the lib root directory.
Simple true/false feature toggles — edit the JSON file manually.
If the file doesn't exist on first load it is auto-created with defaults.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parents[2] / 'pipeline.config.json'

_DEFAULT_CONFIG = {
    "features": {
        "content_templates": False,
        "unique_key": {
            "playerauctions": {"title": True, "description": False},
            "gameboost": {"title": True, "description": False},
            "eldorado": {"title": True, "description": True},
            "g2g": {"title": False, "description": False},
        },
        "fake_password": {
            "valorant": True,
        },
    }
}


@lru_cache(maxsize=1)
def _load_config() -> dict:
    if not _CONFIG_PATH.exists():
        _CONFIG_PATH.write_text(json.dumps(_DEFAULT_CONFIG, indent=2) + '\n')
        return _DEFAULT_CONFIG
    with open(_CONFIG_PATH) as f:
        return json.load(f)


def reload_config() -> None:
    """Clear cached config — call after editing pipeline.config.json."""
    _load_config.cache_clear()


def is_feature_enabled(feature_name: str) -> bool:
    """Check if a feature toggle is enabled."""
    config = _load_config()
    return config.get('features', {}).get(feature_name, False)


def get_unique_key_config(marketplace: str) -> dict[str, bool]:
    """Return unique_key settings for a marketplace.

    Returns dict with 'title' and 'description' booleans.
    """
    config = _load_config()
    uk = config.get('features', {}).get('unique_key', {})
    return uk.get(marketplace.lower(), {"title": False, "description": False})


def is_fake_password_enabled(game: str) -> bool:
    """Check if fake password is enabled for a game."""
    config = _load_config()
    fp = config.get('features', {}).get('fake_password', {})
    return fp.get(game.lower(), False)
