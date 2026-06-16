"""No-op media strategy for PSN accounts."""

from __future__ import annotations

from ..models import PsnResolvedAccount
from .....core.contracts import PipelineRequest


class PsnMediaStrategy:
    """PSN has no generated media — returns an empty list."""

    def prepare(self, subject: PsnResolvedAccount, request: PipelineRequest) -> list[str]:
        return []
