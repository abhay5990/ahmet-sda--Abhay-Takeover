"""No-op media strategy for Rust accounts."""

from __future__ import annotations

from ..models import RustResolvedAccount
from .....core.contracts import PipelineRequest


class RustMediaStrategy:
    """Rust has no generated media — returns an empty list."""

    def prepare(self, subject: RustResolvedAccount, request: PipelineRequest) -> list[str]:
        return []
