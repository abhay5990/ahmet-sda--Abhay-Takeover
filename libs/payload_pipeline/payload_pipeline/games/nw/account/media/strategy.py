"""Media strategy for New World accounts — override-only, no auto-generation."""

from __future__ import annotations

from ..models import NwResolvedAccount
from .....core.capabilities import OVERRIDE_ONLY, MediaCapabilities
from .....core import context_keys as ctx
from .....core.contracts import PipelineRequest
from .....shared.media_override import MediaOverrideMixin


class NwAccountMediaStrategy(MediaOverrideMixin):
    """New World account has no generated media but supports user-selected image overrides."""

    capabilities: MediaCapabilities = OVERRIDE_ONLY

    def prepare(self, subject: NwResolvedAccount, request: PipelineRequest) -> list[str]:
        if bool(request.context.get(ctx.DISABLE_MEDIA)):
            return []

        return self._check_override(request) or []
