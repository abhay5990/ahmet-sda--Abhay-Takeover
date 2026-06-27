"""Resolve Forza Horizon 6 account data from prepared sources."""

from __future__ import annotations

from .models import Fh6ResolvedAccount
from .sources import Fh6ManualSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class Fh6Resolver:
    """Single-source resolver for Forza Horizon 6 accounts."""

    def __init__(self) -> None:
        self._adapter = Fh6ManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> Fh6ResolvedAccount:
        raw = request.source("manual")
        parsed = self._adapter.parse(raw)
        if parsed is None:
            raise SourceValidationError("Forza Horizon 6 requires the 'manual' source.")

        credentials = resolve_credentials(parsed, kind=request.kind, game_name="Forza Horizon 6")

        return Fh6ResolvedAccount(
            item_id=parsed.item_id,
            category_id=parsed.category_id,
            price=parsed.price,
            kind=request.kind,
            credentials=credentials,
            manual_title=parsed.title,
            manual_description=parsed.description,
        )
