"""Centralised output and cache path resolution for payload_pipeline.

Resolution order (first non-empty wins):

1. **Explicit override** — ``request.context[ctx.MEDIA_OUTPUT_DIR]`` or
   ``request.context[ctx.CACHE_BASE_DIR]`` passed per-request.
2. **Environment variable** — ``PAYLOAD_PIPELINE_OUTPUT_DIR`` points to the
   root output directory.  Game/purpose sub-directories are appended
   automatically (e.g. ``<root>/valorant/images``, ``<root>/cache/valorant``).
3. **CWD-relative default** — ``<cwd>/output/payload_pipeline/…``.  This is
   the safest portable default because it writes next to where the process
   runs, not next to the installed package.

Game slugs match the canonical values from ``backend/data/game_mapp.json``.

All helpers return **str** paths so they can be used as function-parameter
defaults without importing Path at every call site.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_KEY = "PAYLOAD_PIPELINE_OUTPUT_DIR"


def _output_root() -> Path:
    """Resolve the base output directory (no game/purpose suffix)."""
    env = os.environ.get(_ENV_KEY, "").strip()
    if env:
        return Path(env)
    return Path.cwd() / "output" / "payload_pipeline"


def default_media_output_dir(game: str, suffix: str = "") -> str:
    """Default media output directory for *game*.

    >>> default_media_output_dir("rainbow-six-siege")
    '.../output/payload_pipeline/rainbow-six-siege/images'
    >>> default_media_output_dir("valorant", suffix="abc123")
    '.../output/payload_pipeline/valorant/images/abc123'
    """
    base = _output_root() / game / "images"
    if suffix:
        base = base / suffix
    return str(base)


def default_cache_base_dir(game: str) -> str:
    """Default image-cache directory for *game*.

    >>> default_cache_base_dir("rainbow-six-siege")
    '.../output/payload_pipeline/cache/rainbow-six-siege'
    """
    return str(_output_root() / "cache" / game)
