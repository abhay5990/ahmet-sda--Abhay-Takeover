"""GameBoost builder for resolved Forza Horizon 6 accounts.

Verified against the read-only GameBoost account-offer template on 2026-10-01:
- game slug: ``forza-horizon-6``
- account_data: platforms (required array), credits_count, all_cars
"""

from __future__ import annotations

from typing import Any

from ..models import Fh6ResolvedAccount
from .....core.contracts import BuildContext
from .....core.variant_mapping import get_external_id
from .....marketplaces.gameboost import BaseGameBoostBuilder


class Fh6GameBoostBuilder(BaseGameBoostBuilder):
    """Build GameBoost payloads for the Forza Horizon 6 account slice."""

    @property
    def game_slug(self) -> str:
        return "forza-horizon-6"

    def _build_account_data(
        self, account: Fh6ResolvedAccount, ctx: BuildContext | None = None,
    ) -> dict[str, Any]:
        gameboost_platform = get_external_id(
            ctx.variant_context if ctx else None, "platform", account.platform,
        ) or account.platform

        all_cars = account.all_cars
        if isinstance(all_cars, str):
            all_cars = all_cars.strip().lower() in {"1", "true", "yes"}
        else:
            all_cars = bool(all_cars)

        account_data: dict[str, Any] = {"all_cars": all_cars}
        if gameboost_platform:
            account_data["platforms"] = [gameboost_platform]
        if account.credits_count:
            account_data["credits_count"] = account.credits_count
        return account_data
