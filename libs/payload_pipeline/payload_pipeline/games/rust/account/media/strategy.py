"""Media strategy for Rust accounts."""

from __future__ import annotations

import logging
from pathlib import Path

from ..models import RustResolvedAccount
from .....core.contracts import PipelineRequest
from .....core import context_keys as ctx

logger = logging.getLogger(__name__)


class RustMediaStrategy:
    """Rust has no generated media, but supports user-selected image overrides."""

    def prepare(self, subject: RustResolvedAccount, request: PipelineRequest) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []

        override = request.context.get(ctx.MEDIA_OVERRIDE_PATH)
        if isinstance(override, str) and override.strip():
            path = Path(override)
            if path.is_file():
                return [str(path)]
            logger.warning("Rust media override path does not exist: %s", override)

        return []
