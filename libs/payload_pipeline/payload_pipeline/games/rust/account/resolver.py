"""Resolve Rust account data from prepared sources."""

from __future__ import annotations

from .models import RustResolvedAccount
from .sources import RustManualSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class RustResolver:
    """Single-source resolver for Rust accounts."""

    def __init__(self) -> None:
        self._adapter = RustManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> RustResolvedAccount:
        raw = request.source("manual")
        parsed = self._adapter.parse(raw)
        if parsed is None:
            raise SourceValidationError("Rust requires the 'manual' source.")

        credentials = resolve_credentials(parsed, kind=request.kind, game_name="Rust")

        return RustResolvedAccount(
            item_id=parsed.item_id,
            category_id=parsed.category_id,
            price=parsed.price,
            kind=request.kind,
            credentials=credentials,
            manual_title=parsed.title,
            manual_description=parsed.description,
            platform=parsed.platform,
            premium_status=parsed.premium_status,
            hours_range=parsed.hours_range,
            skins_range=parsed.skins_range,
            steam_level_range=parsed.steam_level_range,
            real_hours=parsed.real_hours,
            skins_count=parsed.skins_count,
            steam_level=parsed.steam_level,
        )
