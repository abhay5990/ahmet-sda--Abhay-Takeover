"""Reusable G2G base builder.

Extracts the ~30 lines of boilerplate that every game-specific G2G builder
repeats: static payload skeleton, ``_apply_pricing``, ``_build_image_mapping``,
and ``_build_softpin``.  Game slices subclass and override only the parts that
differ (``brand_id``, ``_build_offer_attributes``, price rounding).
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Any

from ..core.contracts import BuildContext, CredentialBundle, ListingDraft
from ..core.exceptions import PayloadPipelineError
from .base import BasePayloadBuilder


_DEFAULT_SERVICE_ID = "f6a1aba5-473a-4044-836a-8968bbab16d7"


@dataclass(slots=True)
class G2GConfig:
    """Marketplace-specific configuration for G2G builders."""

    seller_id: str = ""
    service_id: str = ""


class BaseG2GBuilder(BasePayloadBuilder[Any]):
    """Common shape for G2G account payloads.

    Subclasses **must** implement:
    * ``brand_id`` — the G2G brand identifier for the game.
    * ``_build_offer_attributes`` — game-specific attribute list.

    Subclasses **may** override:
    * ``_round_price`` — default applies ``round(max(price, 0.1), 2)``.
      CS2 / Steam / Roblox override to pass price through unchanged.
    """

    marketplace = "g2g"

    @property
    @abstractmethod
    def brand_id(self) -> str:
        """G2G brand identifier (e.g. ``lgc_game_24333``)."""

    @abstractmethod
    def _build_offer_attributes(
        self,
        subject: Any,
    ) -> list[dict[str, str]]:
        """Return the game-specific ``offer_attributes`` list."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_payload(
        self,
        subject: Any,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> dict[str, Any]:
        content = listing.content_for(self.marketplace, ref_key=subject.ref_key)
        price = self._apply_pricing(subject.price, ctx)

        config = ctx.get_config(G2GConfig)

        seller_id = config.seller_id
        if not seller_id:
            raise PayloadPipelineError(
                "G2G seller_id is required. "
                "Pass it via G2GConfig.seller_id in BuildContext.marketplace_config."
            )
        service_id = config.service_id or _DEFAULT_SERVICE_ID

        payload: dict[str, Any] = {
            "seller_id": seller_id,
            "delivery_method_ids": ["instant_inventory"],
            "delivery_speed": "instant",
            "delivery_speed_details": [],
            "qty": 0,
            "description": content.description,
            "currency": "USD",
            "min_qty": 1,
            "low_stock_alert_qty": 0,
            "sales_territory_settings": {
                "settings_type": "global",
                "countries": [],
            },
            "package_settings": [],
            "title": content.title,
            "offer_attributes": self._build_offer_attributes(subject),
            "external_images_mapping": self._build_image_mapping(listing),
            "unit_price": self._round_price(price),
            "other_pricing": [],
            "wholesale_details": [],
            "other_wholesale_details": [],
            "service_id": service_id,
            "brand_id": self.brand_id,
            "offer_type": "public",
        }

        if self._include_softpin:
            payload["softpin_data"] = self._build_softpin(subject.credentials)
        return payload

    # ------------------------------------------------------------------
    # Overridable hooks
    # ------------------------------------------------------------------

    def _round_price(self, price: float) -> float:
        """Round price for G2G.  Override for games that use raw price."""
        return round(max(price, 0.1), 2)

    @property
    def _include_softpin(self) -> bool:
        """Whether to include softpin_data in the payload dict.

        Some games expose softpin via a separate ``prepare_softpin_data``
        method instead of embedding it in the payload.
        """
        return True

    # ------------------------------------------------------------------
    # Shared helpers (identical across all games)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_image_mapping(listing: ListingDraft) -> list[dict[str, str]]:
        images: list[dict[str, str]] = []
        if listing.media.external_urls:
            for idx, url in enumerate(listing.media.external_urls):
                images.append({"image_name": f"image_{idx + 1}", "image_url": url})
        elif listing.media.album_url:
            images.append({"image_name": "album", "image_url": listing.media.album_url})
        return images

    @staticmethod
    def _build_softpin(credentials: CredentialBundle) -> str:
        username = credentials.login or ""
        password = credentials.password if credentials.password != "1" else "noneedpsswd"
        email = credentials.email_login or "unknown@gmail.com"
        email_password = credentials.email_password or "unknown"

        note = ""
        if credentials.email_login_link:
            note += f"The email login link is --->\n\t{credentials.email_login_link}\n"
        note += (
            "Important: Do not make any dispute or leave negative feedback "
            "before we contact you in case of any problem. We resolve all issues for sure!"
        )

        return f'{username},{password},,,,,,,,{email},{email_password},"{note}"\r\n'
