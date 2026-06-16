"""Resolve New World item data from prepared sources."""

from __future__ import annotations

from .models import NwResolvedItem
from .sources import NwItemManualSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class NwItemResolver:
    """Single-source resolver for New World items."""

    def __init__(self) -> None:
        self._adapter = NwItemManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> NwResolvedItem:
        raw = request.source("manual")
        parsed = self._adapter.parse(raw)
        if parsed is None:
            raise SourceValidationError("New World item requires the 'manual' source.")

        credentials = resolve_credentials(parsed, kind=request.kind, game_name="New World Item")

        return NwResolvedItem(
            item_id=parsed.item_id,
            category_id=parsed.category_id,
            price=parsed.price,
            kind=request.kind,
            credentials=credentials,
            region=parsed.region,
        )
