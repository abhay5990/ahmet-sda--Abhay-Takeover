"""Static media helpers for account slices with bundled images."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core import context_keys as ctx
from ..core.contracts import PipelineRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StaticMediaSpec:
    """Configuration for a single bundled static media asset."""

    resource_path: Path


class StaticAccountMediaStrategy:
    """Expose one bundled account image without per-item output copies."""

    def __init__(self, spec: StaticMediaSpec) -> None:
        self._spec = spec

    def prepare(self, subject: Any, request: PipelineRequest) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []

        resource_path = resolve_static_media_resource(self._spec.resource_path)
        return [resource_path] if resource_path else []


def resolve_static_media_resource(resource_path: Path | str) -> str | None:
    """Return the absolute path for a bundled static media asset."""

    source = Path(resource_path).resolve()
    if not source.is_file():
        logger.warning("Static media resource is missing: %s", source)
        return None

    return str(source)
