"""Resolve CS2 account data from prepared sources."""

from __future__ import annotations

from .models import CS2ResolvedAccount
from .sources import CS2LztSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class CS2Resolver:
    """Simple single-source resolver for the CS2 slice."""

    def __init__(self) -> None:
        self.lzt = CS2LztSourceAdapter()

    def resolve(self, request: PipelineRequest) -> CS2ResolvedAccount:
        lzt = self.lzt.parse(request.source("lzt"))
        if lzt is None:
            raise SourceValidationError("CS2 requires the 'lzt' source.")

        credentials = resolve_credentials(lzt, kind=request.kind, game_name="CS2")

        return CS2ResolvedAccount(
            item_id=lzt.item_id,
            category_id=lzt.category_id,
            price=lzt.price,
            kind=request.kind,
            credentials=credentials,
            rank=lzt.rank,
            rank_id=lzt.rank_id,
            premier_elo=lzt.premier_elo,
            medals=lzt.medals,
            is_prime=lzt.is_prime,
            has_email_access=not lzt.credentials.is_empty and bool(lzt.credentials.email_login),
            hours_played=lzt.hours_played,
            games=lzt.games,
        )
