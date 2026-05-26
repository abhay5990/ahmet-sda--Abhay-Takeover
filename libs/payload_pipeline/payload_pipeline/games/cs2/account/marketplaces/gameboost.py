"""GameBoost builder for resolved CS2 accounts."""

from __future__ import annotations

from typing import Any

from ..models import CS2ResolvedAccount
from .....marketplaces.gameboost import BaseGameBoostBuilder


class CS2GameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the CS2 account slice."""

    @property
    def game_slug(self) -> str:
        return "counter-strike-2"

    @property
    def _platform_name(self) -> str:
        return "Steam Account"

    def _build_account_data(self, account: CS2ResolvedAccount, ctx=None) -> dict[str, Any]:
        return {
            "premier_rating_count": account.premier_elo,
            "hours_played_count": account.hours_played,
            "veteran_coin": "",
            "prime_enabled": account.is_prime,
            "trade_banned": False,
        }

    def _build_dump(self, account: CS2ResolvedAccount) -> str | None:
        tags = self._build_dump_tags(account)
        return tags if tags else None

    # ------------------------------------------------------------------
    # Game-specific helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_dump_tags(account: CS2ResolvedAccount) -> str:
        parts = [
            "prime cs2 account" if account.is_prime else "no prime",
            "",  # steam_cs2_rank_name — not available in resolved model, matches legacy default
            f"{account.premier_elo} PR" if account.premier_elo else None,
            f"{account.hours_played} hours" if account.hours_played else None,
            "",  # veteran_coin — not available in resolved model, matches legacy default
        ]
        return ", ".join(filter(None, parts))
