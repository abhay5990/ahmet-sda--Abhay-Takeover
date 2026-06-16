"""No-op media strategy for New World items."""

from __future__ import annotations

from ..models import NwResolvedItem
from .....core.contracts import PipelineRequest


class NwItemMediaStrategy:
    """New World items have no generated media — returns an empty list."""

    def prepare(self, subject: NwResolvedItem, request: PipelineRequest) -> list[str]:
        return []
