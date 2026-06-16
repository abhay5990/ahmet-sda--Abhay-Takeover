"""No-op media strategy for Xbox accounts."""

from __future__ import annotations

from ..models import XboxResolvedAccount
from .....core.contracts import PipelineRequest


class XboxMediaStrategy:
    """Xbox has no generated media — returns an empty list."""

    def prepare(self, subject: XboxResolvedAccount, request: PipelineRequest) -> list[str]:
        return []
