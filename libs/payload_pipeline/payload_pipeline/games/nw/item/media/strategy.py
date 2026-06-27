"""Media strategy for New World items — override-only, no auto-generation."""

from __future__ import annotations

from ..models import NwResolvedItem
from .....core.capabilities import OVERRIDE_ONLY, MediaCapabilities
from .....core import context_keys as ctx
from .....core.contracts import PipelineRequest
from .....shared.media_override import MediaOverrideMixin


class NwItemMediaStrategy(MediaOverrideMixin):
    """New World items have no generated media but support user-selected image overrides."""

    capabilities: MediaCapabilities = OVERRIDE_ONLY

    def prepare(self, subject: NwResolvedItem, request: PipelineRequest) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []

        return self._check_override(request) or []
