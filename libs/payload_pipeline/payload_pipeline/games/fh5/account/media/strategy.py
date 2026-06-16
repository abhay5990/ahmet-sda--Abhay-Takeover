"""No-op media strategy for Forza Horizon 5 accounts."""

from __future__ import annotations

from ..models import Fh5ResolvedAccount
from .....core.contracts import PipelineRequest


class Fh5MediaStrategy:
    """Forza Horizon 5 has no generated media — returns an empty list."""

    def prepare(self, subject: Fh5ResolvedAccount, request: PipelineRequest) -> list[str]:
        return []
