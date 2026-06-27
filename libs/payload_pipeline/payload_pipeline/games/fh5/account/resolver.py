"""Resolve Forza Horizon 5 account data from prepared sources."""

from __future__ import annotations

from .models import Fh5ResolvedAccount
from .sources import Fh5ManualSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class Fh5Resolver:
    """Single-source resolver for Forza Horizon 5 accounts."""

    def __init__(self) -> None:
        self._adapter = Fh5ManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> Fh5ResolvedAccount:
        raw = request.source("manual")
        parsed = self._adapter.parse(raw)
        if parsed is None:
            raise SourceValidationError("Forza Horizon 5 requires the 'manual' source.")

        credentials = resolve_credentials(parsed, kind=request.kind, game_name="Forza Horizon 5")

        return Fh5ResolvedAccount(
            item_id=parsed.item_id,
            category_id=parsed.category_id,
            price=parsed.price,
            kind=request.kind,
            credentials=credentials,
            platform=parsed.platform,
            edition=parsed.edition,
            cars_count=parsed.cars_count,
            credits_count=parsed.credits_count,
            manual_title=parsed.title,
            manual_description=parsed.description,
        )
