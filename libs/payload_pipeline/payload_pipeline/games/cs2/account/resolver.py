"""Resolve CS2 account data from prepared sources."""

from __future__ import annotations

from .models import CS2ResolvedAccount
from .sources import CS2LztSourceAdapter, CS2ManualSourceAdapter
from ....core.contracts import PipelineRequest
from ....core.exceptions import SourceValidationError
from ....shared.credentials import resolve_credentials


class CS2Resolver:
    """Multi-source resolver for CS2 (manual + LZT)."""

    def __init__(self) -> None:
        self._lzt = CS2LztSourceAdapter()
        self._manual = CS2ManualSourceAdapter()

    def resolve(self, request: PipelineRequest) -> CS2ResolvedAccount:
        # Try manual source first
        manual = self._manual.parse(request.source("manual"))
        if manual is not None:
            return self._resolve_manual(manual, request)

        # Fall back to LZT source
        lzt = self._lzt.parse(request.source("lzt"))
        if lzt is None:
            raise SourceValidationError("CS2 requires a 'manual' or 'lzt' source.")

        return self._resolve_lzt(lzt, request)

    def _resolve_manual(self, src, request: PipelineRequest) -> CS2ResolvedAccount:
        credentials = resolve_credentials(src, kind=request.kind, game_name="CS2")

        return CS2ResolvedAccount(
            item_id=src.item_id,
            category_id=src.category_id,
            price=src.price,
            kind=request.kind,
            credentials=credentials,
            manual_title=src.title,
            manual_description=src.description,
            is_prime=src.prime_status == "active-prime",
            has_email_access=not credentials.is_empty and bool(credentials.email_login),
            premier_elo=src.premier_rating,
            medal_count_manual=src.medals,
            # Pass manual attribute slugs for marketplace builders
            prime_attr=src.prime_status if src.prime_status != "other" else "",
            veteran_coin_attr=src.veteran_coin if src.veteran_coin != "other" else "",
            esea_attr=src.esea_rating if src.esea_rating != "other" else "",
            faceit_attr=src.faceit_level if src.faceit_level != "other" else "",
        )

    def _resolve_lzt(self, lzt, request: PipelineRequest) -> CS2ResolvedAccount:
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
