"""Reusable media-override mixin for game strategies."""

from __future__ import annotations

import logging
from pathlib import Path

from ..core import context_keys as ctx
from ..core.contracts import PipelineRequest

logger = logging.getLogger(__name__)


class MediaOverrideMixin:
    """Mixin that checks for a user-selected image override.

    Any media strategy that includes this mixin can call
    ``_check_override(request)`` at the top of ``prepare()`` to
    short-circuit with the user's chosen image when present.

    Returns:
        A single-element list with the override path if valid,
        or ``None`` so the caller can fall through to its own logic.
    """

    def _check_override(self, request: PipelineRequest) -> list[str] | None:
        override = request.context.get(ctx.MEDIA_OVERRIDE_PATH)
        if not isinstance(override, str) or not override.strip():
            return None

        path = Path(override)
        if path.is_file():
            return [str(path)]

        logger.warning("Media override path does not exist: %s", override)
        return None
