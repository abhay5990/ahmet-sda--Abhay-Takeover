"""Resolve Xbox account data from prepared sources."""

from __future__ import annotations

from .models import XboxResolvedAccount
from .sources import XboxManualSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class XboxResolver:
    """Single-source resolver for Xbox accounts."""

    def __init__(self) -> None:
        self._adapter = XboxManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> XboxResolvedAccount:
        raw = request.source("manual")
        parsed = self._adapter.parse(raw)
        if parsed is None:
            raise SourceValidationError("Xbox requires the 'manual' source.")

        credentials = resolve_credentials(parsed, kind=request.kind, game_name="Xbox")

        return XboxResolvedAccount(
            item_id=parsed.item_id,
            category_id=parsed.category_id,
            price=parsed.price,
            kind=request.kind,
            credentials=credentials,
        )
