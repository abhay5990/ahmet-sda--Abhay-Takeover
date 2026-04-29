"""Centralized output and cache path resolution for payload_pipeline.

Resolution order:

1. Explicit override values passed through request context.
2. ``PAYLOAD_PIPELINE_OUTPUT_DIR`` as the root output directory.
3. The repository root ``output`` directory.

The default layout is:

* ``output/<game>/images[/suffix]`` for generated images.
* ``output/<game>/files[/suffix]`` for generated files.
* ``output/<game>/image-cache`` for downloaded image cache files.

Static bundled resources such as ``resources/image_map`` are not cache output
and should stay next to their owning package.
"""

from __future__ import annotations

import os
from pathlib import Path

_ENV_KEY = "PAYLOAD_PIPELINE_OUTPUT_DIR"


def _output_root() -> Path:
    """Resolve the base output directory without game/purpose suffixes."""
    env = os.environ.get(_ENV_KEY, "").strip()
    if env:
        return Path(env).expanduser()
    return _project_root() / "output"


def _project_root() -> Path:
    """Find the repository root from the current process or this file path."""
    starts = [Path.cwd(), Path(__file__).resolve()]
    for start in starts:
        current = start if start.is_dir() else start.parent
        for candidate in (current, *current.parents):
            if _looks_like_repo_root(candidate):
                return candidate
    return Path.cwd()


def _looks_like_repo_root(path: Path) -> bool:
    if (path / ".git").exists():
        return True
    return (path / "backend").is_dir() and (path / "libs").is_dir()


def default_media_output_dir(game: str, suffix: str = "") -> str:
    """Default generated-image directory for *game*.

    >>> default_media_output_dir("clash-royale")
    '.../output/clash-royale/images'
    >>> default_media_output_dir("valorant", suffix="abc123")
    '.../output/valorant/images/abc123'
    """
    return str(_with_optional_suffix(_output_root() / game / "images", suffix))


def default_file_output_dir(game: str, suffix: str = "") -> str:
    """Default generated-file directory for *game*."""
    return str(_with_optional_suffix(_output_root() / game / "files", suffix))


def default_cache_base_dir(game: str) -> str:
    """Default downloaded image-cache directory for *game*.

    >>> default_cache_base_dir("clash-royale")
    '.../output/clash-royale/image-cache'
    """
    return str(_output_root() / game / "image-cache")


def _with_optional_suffix(base: Path, suffix: str) -> Path:
    suffix = suffix.strip() if isinstance(suffix, str) else ""
    return base / suffix if suffix else base
