"""
Eldorado mapper.

Provides helpers for building Eldorado API payloads and extracting
structured data from API responses.

Canonical marketplace-level DTOs (to_canonical_offer, to_canonical_order)
are still deferred — they require a shared marketplace model layer that
does not yet exist. The helpers here work with Eldorado-native models.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.clients.marketplaces.eldorado.models import (
    EldoradoOffer,
    EldoradoOfferImage,
)


class EldoradoMapper:
    """
    Mapper for Eldorado API payloads and responses.

    Implemented:
    - to_create_payload: builds the offer creation payload dict
    - to_update_payload: builds the offer update payload dict
    - extract_image_keys: extracts S3 keys from upload response

    Deferred to phase 3 (requires shared marketplace canonical models):
    - to_canonical_offer
    - to_canonical_order
    """

    @staticmethod
    def to_create_payload(
        *,
        game_id: str,
        category: str = "Account",
        title: str,
        description: str,
        price_amount: float,
        price_currency: str = "USD",
        quantity: int = 1,
        min_quantity: int = 1,
        delivery_time: str = "Instant",
        main_image: EldoradoOfferImage | None = None,
        additional_images: list[EldoradoOfferImage] | None = None,
        has_original_email: bool = False,
        trade_environment_id: str | None = None,
        attribute_ids_csv: str = "",
        attributes: dict[str, str] | None = None,
        account_secret_details: str | list[str] = "",
        tags: list[str] | None = None,
        volume_discounts: list[dict[str, object]] | None = None,
    ) -> dict[str, Any]:
        """
        Build an Eldorado offer creation payload.

        Returns the dict structure expected by POST /api/flexibleOffers/account.
        """
        main_img = (main_image or EldoradoOfferImage()).model_dump()

        payload: dict[str, Any] = {
            "details": {
                "pricing": {
                    "quantity": quantity,
                    "minQuantity": min_quantity,
                    "pricePerUnit": {
                        "amount": price_amount,
                        "currency": price_currency,
                    },
                    "volumeDiscounts": volume_discounts or [],
                },
                "description": description,
                "guaranteedDeliveryTime": delivery_time,
                "offerTitle": title,
                "mainOfferImage": main_img,
                "offerImages": [img.model_dump() for img in (additional_images or [])],
                "hasOriginalEmail": has_original_email,
                "tags": tags or [],
            },
            "augmentedGame": {
                "gameId": game_id,
                "category": category,
                "tradeEnvironmentId": trade_environment_id,
                "attributeIdsCsv": attribute_ids_csv,
                "attributes": attributes or {},
            },
            "accountSecretDetails": account_secret_details,
        }
        return payload

    @staticmethod
    def to_update_payload(
        offer: EldoradoOffer,
        *,
        price_amount: float | None = None,
        title: str | None = None,
        description: str | None = None,
        delivery_time: str | None = None,
        account_secret_details: str | list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Build an Eldorado offer update payload from an existing offer.

        Only overrides fields that are explicitly provided.
        """
        payload = offer.model_dump()

        if price_amount is not None:
            payload["details"]["pricing"]["pricePerUnit"]["amount"] = price_amount
        if title is not None:
            payload["details"]["offerTitle"] = title
        if description is not None:
            payload["details"]["description"] = description
        if delivery_time is not None:
            payload["details"]["guaranteedDeliveryTime"] = delivery_time
        if account_secret_details is not None:
            payload["accountSecretDetails"] = account_secret_details

        return payload

    @staticmethod
    def extract_image_keys(upload_paths: list[str]) -> EldoradoOfferImage | None:
        """
        Extract an EldoradoOfferImage from upload response paths.

        The Eldorado upload API returns paths like '/offerimages/key'.
        This strips the prefix and maps to the triplet structure.

        Returns None if not enough paths are provided.
        """
        cleaned = [p.replace("/offerimages/", "") for p in upload_paths]
        if len(cleaned) < 3:
            return None
        return EldoradoOfferImage(
            smallImage=cleaned[0],
            largeImage=cleaned[1],
            originalSizeImage=cleaned[2],
        )

    @staticmethod
    def build_from_raw(
        raw_data: dict[str, Any],
        *,
        exclude_credential_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        """Build a create_offer payload from raw Eldorado API data.

        Takes the flat structure stored in RawPayload (search/list endpoint
        format) and converts it to the nested structure expected by
        POST /api/flexibleOffers/account.

        Args:
            raw_data: Raw offer dict from Eldorado API (search format).
            exclude_credential_ids: Credential entry IDs to exclude
                (e.g. sold accounts).  Matched against
                ``_credential_entries[*].id``.

        Returns:
            Ready-to-send payload dict for ``create_offer()``.
        """
        exclude = exclude_credential_ids or set()

        # --- credentials ------------------------------------------------
        credential_entries = raw_data.get("_credential_entries") or []
        secrets: list[str] = [
            entry["secretDetails"]
            for entry in credential_entries
            if entry.get("id") not in exclude and entry.get("secretDetails")
        ]
        quantity = len(secrets)

        # --- images -----------------------------------------------------
        raw_main = raw_data.get("mainOfferImage") or {}
        main_image = EldoradoOfferImage(
            smallImage=raw_main.get("smallImage", ""),
            largeImage=raw_main.get("largeImage", ""),
            originalSizeImage=raw_main.get("originalSizeImage", ""),
        ) if raw_main else None

        raw_images = raw_data.get("offerImages") or []
        additional_images = [
            EldoradoOfferImage(
                smallImage=img.get("smallImage", ""),
                largeImage=img.get("largeImage", ""),
                originalSizeImage=img.get("originalSizeImage", ""),
            )
            for img in raw_images
        ] or None

        # --- trade environment ------------------------------------------
        trade_envs = raw_data.get("tradeEnvironmentValues") or []
        trade_env_id = trade_envs[0]["id"] if trade_envs else None

        # --- attributes -------------------------------------------------
        # Raw format: [{"id": "fortnite-account-type", "value": {"id": "og-account"}}]
        # Payload format: {"fortnite-account-type": "og-account"}
        raw_attrs = raw_data.get("attributes") or []
        attributes: dict[str, str] = {}
        for attr in raw_attrs:
            attr_id = attr.get("id", "")
            value_obj = attr.get("value")
            if attr_id and isinstance(value_obj, dict):
                attributes[attr_id] = value_obj.get("id", "")

        # --- price ------------------------------------------------------
        price_obj = raw_data.get("pricePerUnit") or {}
        price_amount = float(price_obj.get("amount", 0))
        price_currency = price_obj.get("currency", "USD")

        return EldoradoMapper.to_create_payload(
            game_id=str(raw_data.get("gameId", "")),
            category=raw_data.get("category", "Account"),
            title=raw_data.get("offerTitle", ""),
            description=raw_data.get("description", ""),
            price_amount=price_amount,
            price_currency=price_currency,
            quantity=quantity,
            min_quantity=raw_data.get("minQuantity", 1),
            delivery_time=raw_data.get("guaranteedDeliveryTime", "Instant"),
            main_image=main_image,
            additional_images=additional_images,
            has_original_email=raw_data.get("hasOriginalEmail", False) or False,
            trade_environment_id=trade_env_id,
            attributes=attributes or None,
            volume_discounts=raw_data.get("volumeDiscounts") or None,
            account_secret_details=secrets,
        )

    @staticmethod
    def to_canonical_offer(*args: object, **kwargs: object) -> object:
        """Deferred to phase 3 — requires shared marketplace canonical models."""
        raise NotImplementedError(
            "EldoradoMapper.to_canonical_offer is deferred to phase 3 "
            "(requires shared marketplace-level canonical DTOs).",
        )

    @staticmethod
    def to_canonical_order(*args: object, **kwargs: object) -> object:
        """Deferred to phase 3 — requires shared marketplace canonical models."""
        raise NotImplementedError(
            "EldoradoMapper.to_canonical_order is deferred to phase 3 "
            "(requires shared marketplace-level canonical DTOs).",
        )
