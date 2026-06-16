"""No-op media strategy for New World accounts."""

from __future__ import annotations

from ..models import NwResolvedAccount
from .....core.contracts import PipelineRequest


class NwAccountMediaStrategy:
    """New World account has no generated media — returns an empty list."""

    def prepare(self, subject: NwResolvedAccount, request: PipelineRequest) -> list[str]:
        return []
