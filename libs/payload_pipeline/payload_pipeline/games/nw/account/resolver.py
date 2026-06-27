"""Resolve New World account data from prepared sources."""

from __future__ import annotations

from .models import NwResolvedAccount
from .sources import NwManualSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class NwAccountResolver:
    """Single-source resolver for New World accounts."""

    def __init__(self) -> None:
        self._adapter = NwManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> NwResolvedAccount:
        raw = request.source("manual")
        parsed = self._adapter.parse(raw)
        if parsed is None:
            raise SourceValidationError("New World requires the 'manual' source.")

        credentials = resolve_credentials(parsed, kind=request.kind, game_name="New World")

        return NwResolvedAccount(
            item_id=parsed.item_id,
            category_id=parsed.category_id,
            price=parsed.price,
            kind=request.kind,
            credentials=credentials,
            manual_title=parsed.title,
            manual_description=parsed.description,
            region=parsed.region,
        )
