"""Media strategy for Forza Horizon 6 accounts — override-only, no auto-generation."""

from __future__ import annotations

from ..models import Fh6ResolvedAccount
from .....core.capabilities import OVERRIDE_ONLY, MediaCapabilities
from .....core import context_keys as ctx
from .....core.contracts import PipelineRequest
from .....shared.media_override import MediaOverrideMixin


class Fh6MediaStrategy(MediaOverrideMixin):
    """Forza Horizon 6 has no generated media but supports user-selected image overrides."""

    capabilities: MediaCapabilities = OVERRIDE_ONLY

    def prepare(self, subject: Fh6ResolvedAccount, request: PipelineRequest) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []

        return self._check_override(request) or []
