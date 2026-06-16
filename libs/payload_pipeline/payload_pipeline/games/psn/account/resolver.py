"""Resolve PSN account data from prepared sources."""

from __future__ import annotations

from .models import PsnResolvedAccount
from .sources import PsnManualSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class PsnResolver:
    """Single-source resolver for PSN accounts."""

    def __init__(self) -> None:
        self._adapter = PsnManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> PsnResolvedAccount:
        raw = request.source("manual")
        parsed = self._adapter.parse(raw)
        if parsed is None:
            raise SourceValidationError("PSN requires the 'manual' source.")

        credentials = resolve_credentials(parsed, kind=request.kind, game_name="PSN")

        return PsnResolvedAccount(
            item_id=parsed.item_id,
            category_id=parsed.category_id,
            price=parsed.price,
            kind=request.kind,
            credentials=credentials,
        )
