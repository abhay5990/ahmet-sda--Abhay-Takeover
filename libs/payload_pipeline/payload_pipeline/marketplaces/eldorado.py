"""Reusable Eldorado payload helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from ..core.contracts import BuildContext, CredentialBundle, ListingDraft, ListingKind
from .eldorado_media import upload_images_to_eldorado
from .base import BasePayloadBuilder

if TYPE_CHECKING:
    from ..core.contracts import MarketplaceImageUploader


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EldoradoConfig:
    """Marketplace-specific configuration for Eldorado builders."""

    image_uploader: MarketplaceImageUploader | None = None
    image_retries: int = 2


class EldoradoImageUploader:
    """Upload prepared local images to Eldorado via the protocol.

    Accepts an optional ``MarketplaceImageUploader`` at init time, or
    falls back to ``BuildContext.eldorado_image_uploader`` at call time.

    All failures propagate as exceptions — the caller (``build()``) is
    responsible for converting them into a ``PipelineResult(success=False)``.
    """

    def __init__(
        self,
        uploader: MarketplaceImageUploader | None = None,
        *,
        max_retries: int = 2,
    ) -> None:
        self.uploader = uploader
        self.max_retries = max_retries

    def upload(
        self,
        local_paths: Sequence[str],
        ctx: BuildContext | None = None,
    ) -> list[str]:
        """Upload *local_paths* and return formatted URL triples.

        Returns an empty list immediately when *local_paths* is empty —
        callers treat that as "no images".

        Raises ``RuntimeError`` if an uploader is required but not configured.
        All upload exceptions propagate unchanged.
        """
        valid_paths = [str(Path(path)) for path in local_paths if path and Path(path).exists()]
        if not valid_paths:
            return []

        el_config = ctx.get_config(EldoradoConfig) if ctx else None

        uploader = self.uploader or (el_config.image_uploader if el_config else None)
        if uploader is None:
            raise RuntimeError(
                "Eldorado image upload requested but no uploader is configured. "
                "Pass an uploader via EldoradoConfig.image_uploader."
            )

        retries = el_config.image_retries if el_config else self.max_retries

        return upload_images_to_eldorado(
            image_paths=valid_paths,
            uploader=uploader,
            max_retries=retries,
        )


class BaseEldoradoBuilder(BasePayloadBuilder[Any]):
    """Build the common shape for Eldorado account payloads."""

    marketplace = "eldorado"

    def __init__(self, image_uploader: EldoradoImageUploader | None = None) -> None:
        self.image_uploader = image_uploader or EldoradoImageUploader()

    def build_base_payload(
        self,
        *,
        game_id: str,
        listing: ListingDraft,
        ctx: BuildContext,
        price: float,
        credentials: CredentialBundle,
        trade_environment_id: str | None = None,
        attributes: dict[str, Any] | None = None,
        ref_key: str = "",
    ) -> dict[str, Any]:
        is_dropship = ctx.kind == ListingKind.DROPSHIPPING
        final_price = self._apply_pricing(price, ctx)
        content = listing.content_for(self.marketplace, ref_key=ref_key)

        # Pricing block — dropship omits minQuantity and volumeDiscounts
        if is_dropship:
            pricing_block: dict[str, Any] = {
                "quantity": 1,
                "pricePerUnit": {
                    "amount": round(max(final_price, 0.1), 2),
                    "currency": "USD",
                },
            }
        else:
            pricing_block = {
                "quantity": 1,
                "minQuantity": 1,
                "pricePerUnit": {
                    "amount": round(max(final_price, 0.1), 2),
                    "currency": "USD",
                },
                "volumeDiscounts": [],
            }

        payload: dict[str, Any] = {
            "details": {
                "pricing": pricing_block,
                "description": content.description,
                "guaranteedDeliveryTime": "Minute20" if is_dropship else "Instant",
                "offerTitle": content.title,
                "mainOfferImage": {},
                "offerImages": [],
                "hasOriginalEmail": False,
            },
            "augmentedGame": {
                "gameId": game_id,
                "category": "Account",
                "tradeEnvironmentId": trade_environment_id,
                "attributeIdsCsv": None,
            },
        }

        # Credentials — dropship never sends account secrets
        if not is_dropship:
            payload["accountSecretDetails"] = []
            if not credentials.is_empty:
                payload["accountSecretDetails"] = [credentials.to_multiline()]

        # Attributes — Eldorado expects offerAttributes array format
        if attributes:
            payload["augmentedGame"]["offerAttributes"] = [
                {"id": attr_id, "type": "Select", "value": attr_value}
                for attr_id, attr_value in attributes.items()
            ]

        self._attach_uploaded_images(payload, listing=listing, ctx=ctx)
        return payload

    def _attach_uploaded_images(
        self,
        payload: dict[str, Any],
        *,
        listing: ListingDraft,
        ctx: BuildContext,
    ) -> None:
        """Upload listing images and attach them to *payload*.

        If there are no local image paths this is a no-op — no images is
        a valid state (e.g. listings without screenshots).

        Raises ``RuntimeError`` if images exist but the upload returns
        fewer than 3 formatted paths (small/large/original per image).
        """
        if not listing.media.local_paths:
            return

        formatted_paths = self.image_uploader.upload(listing.media.local_paths[:5], ctx=ctx)
        if len(formatted_paths) < 3:
            raise RuntimeError(
                f"Eldorado image upload returned {len(formatted_paths)} path(s); "
                f"expected at least 3 (small, large, original) for 1 image."
            )

        payload["details"]["mainOfferImage"] = {
            "smallImage": formatted_paths[0],
            "largeImage": formatted_paths[1],
            "originalSizeImage": formatted_paths[2],
        }

        for index in range(3, len(formatted_paths), 3):
            if index + 2 >= len(formatted_paths):
                break
            payload["details"]["offerImages"].append(
                {
                    "smallImage": formatted_paths[index],
                    "largeImage": formatted_paths[index + 1],
                    "originalSizeImage": formatted_paths[index + 2],
                }
            )
