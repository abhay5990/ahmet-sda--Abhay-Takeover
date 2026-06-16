"""No-op media strategy for Forza Horizon 6 accounts."""

from __future__ import annotations

from ..models import Fh6ResolvedAccount
from .....core.contracts import PipelineRequest


class Fh6MediaStrategy:
    """Forza Horizon 6 has no generated media — returns an empty list."""

    def prepare(self, subject: Fh6ResolvedAccount, request: PipelineRequest) -> list[str]:
        return []
