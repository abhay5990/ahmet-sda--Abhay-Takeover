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
        "ref_key_in_description": True,
        "content_templates": False,
        "title_hash_suffix": True,
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
