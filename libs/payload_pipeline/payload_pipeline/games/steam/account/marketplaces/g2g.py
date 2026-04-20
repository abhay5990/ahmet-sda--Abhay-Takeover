"""G2G builder for resolved Steam accounts (stock only)."""

from __future__ import annotations

from typing import Any

from ..models import SteamResolvedAccount
from .....marketplaces.g2g import BaseG2GBuilder


_BRAND_ID = "lgc_game_22539"


class SteamG2GBuilder(BaseG2GBuilder):
    """Build G2G payloads for the Steam account slice (stock only)."""

    @property
    def brand_id(self) -> str:
        return _BRAND_ID

    @property
    def _include_softpin(self) -> bool:
        return False

    def _round_price(self, price: float) -> float:
        return price

    def _build_offer_attributes(
        self,
        subject: Any,
    ) -> list[dict[str, str]]:
        return []

    def prepare_softpin_data(self, account: SteamResolvedAccount) -> str:
        return self._build_softpin(account.credentials)
