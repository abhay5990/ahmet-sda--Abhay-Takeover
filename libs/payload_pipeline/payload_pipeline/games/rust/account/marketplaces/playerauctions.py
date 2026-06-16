"""PlayerAuctions builder for resolved Rust accounts.

Template reference: ``assets/playerauctions_templates/accounts/rust.json``
  - game_id: 6141
  - servers: Main Server (6142)
  - requiredFields: securityQA=true, parentalPassword=true (sent as empty strings)
"""

from __future__ import annotations

from typing import Any

from ..models import RustResolvedAccount
from .....core.contracts import BuildContext, ListingDraft
from .....marketplaces.playerauctions import BasePlayerAuctionsBuilder

_COVER_IMAGE_URL = (
    "https://image-cdn-p.azureedge.net/title-image/Rust/rust_cover.png"
)


class RustPlayerAuctionsBuilder(BasePlayerAuctionsBuilder):
    """Build PlayerAuctions payloads for the Rust account slice."""

    @property
    def game_name(self) -> str:
        return "rust"

    @property
    def _pa_game_display_name(self) -> str:
        return "RUST"

    @property
    def game_id(self) -> int:
        return 6141

    @property
    def cover_image_url(self) -> str:
        return _COVER_IMAGE_URL

    @property
    def _platform_name(self) -> str:
        return "Steam Account"

    def _get_server(
        self, account: RustResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str]:
        return ["Main Server"]

    def _get_server_id(
        self, account: RustResolvedAccount, ctx: BuildContext | None = None,
    ) -> list[str] | None:
        return ["6142"]

    def build_payload(
        self,
        account: RustResolvedAccount,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        return super().build_payload(account, listing, ctx)
