"""U7Buy account-offer payload support.

Manual delivery is the default. Automatic delivery is an explicit, catalog-
verified opt-in that sends one owned account bundle only in U7Buy's documented
``keys[].encrypted`` field. The bundle must never appear in public content,
listing audit data, or logs.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ..core.contracts import BuildContext, ListingDraft
from ..core.variant_mapping import get_external_id


U7BUY_ACCOUNT_BUSINESS_ID = "1820693954263351302"
U7BUY_MANUAL_DELIVERY_ID = "1888166069358653442"
U7BUY_MANUAL_DELIVERY_TIME = "24"


@dataclass(frozen=True, slots=True)
class U7BuyConfig:
    """Store-owned catalog configuration supplied by the encrypted credential.

    ``game_services`` is keyed by SDA game slug.  Each entry must contain the
    U7Buy entity and SPU identifier approved for that exact game.  Optional
    attribute mappings are passed through only when they were read from the
    seller's U7Buy catalog; no IDs are guessed in code.
    """

    game_services: dict[str, dict[str, Any]] = field(default_factory=dict)

    def service_for(self, game_slug: str) -> dict[str, Any]:
        value = self.game_services.get(game_slug) or {}
        if not isinstance(value, dict):
            return {}
        return value


class U7BuyAccountBuilder:
    """Build one owned-account U7Buy offer with a verified delivery mode."""

    def __init__(self, game_slug: str) -> None:
        self.game_slug = game_slug

    def build_payload(self, subject: Any, listing: ListingDraft, ctx: BuildContext) -> dict[str, Any]:
        config = ctx.get_config(U7BuyConfig)
        service = config.service_for(self.game_slug)
        entity_id = str(service.get("entity_id") or "").strip()
        spu_id = str(service.get("spu_id") or "").strip()
        if not entity_id or not spu_id:
            raise ValueError(
                f"U7Buy game service is not configured for {self.game_slug}; "
                "select the verified entity and SPU from the U7Buy catalog first."
            )

        content = listing.content_for("u7buy", getattr(subject, "ref_key", ""))
        title = content.title.strip()
        safe_title = _redact_subject_credentials(title, subject)
        if safe_title != title:
            raise ValueError("U7Buy offer name must not contain account credentials")
        if not title:
            raise ValueError("U7Buy offer name is empty")
        if len(title) > 150:
            title = title[:150].rstrip()
        description = _redact_subject_credentials(content.description or "", subject)

        selected_platform = ""
        if ctx.selected_variants:
            selected_platform = str(ctx.selected_variants.get("platform") or "")
        selected_platform = selected_platform or str(getattr(subject, "main_platform", "") or "")
        configured_platforms = service.get("platform_ids") or {}
        platform_id = ""
        if isinstance(configured_platforms, dict):
            platform_id = str(
                configured_platforms.get(selected_platform)
                or configured_platforms.get(selected_platform.lower())
                or ""
            )
        # A shared variant mapping may already contain a verified U7Buy ID.
        # Never manufacture a platform identifier when neither source has one.
        platform_id = platform_id or get_external_id(ctx.variant_context, "platform", selected_platform)

        price_rule = (ctx.pricing_rules or {}).get("u7buy")
        raw_price = Decimal(str(getattr(subject, "price", 0) or 0))
        if raw_price <= 0:
            raise ValueError("U7Buy offer price must be positive")
        # Stock payload construction already records the computed final price;
        # use the supplied rule here only when this builder is called directly.
        price = raw_price
        if price_rule is not None:
            price = Decimal(str(raw_price * Decimal(str(price_rule.multiplier_low))))
            price = max(price, Decimal(str(price_rule.min_price)))
        if ctx.exchange_rate:
            price *= Decimal(str(ctx.exchange_rate))
        price = price.quantize(Decimal("0.01"))

        delivery_mode = str(service.get("delivery_mode") or "manual").strip().lower()
        if delivery_mode not in {"manual", "automatic"}:
            raise ValueError("U7Buy delivery_mode must be either manual or automatic")

        payload: dict[str, Any] = {
            "entityId": entity_id,
            "spuId": spu_id,
            "businessId": str(service.get("business_id") or U7BUY_ACCOUNT_BUSINESS_ID),
            "offerName": title,
            "description": description,
            "priceUsd": f"{price:.2f}",
            "stockPrice": f"{price:.2f}",
            "inventory": 1,
            "inventoryWarning": 1,
        }
        if delivery_mode == "automatic":
            if service.get("automatic_delivery_enabled") is not True:
                raise ValueError(
                    "U7Buy automatic delivery is disabled; enable it only after "
                    "a seller catalog read confirms the exact SPU delivery type."
                )
            automatic_delivery_type_id = str(service.get("automatic_delivery_type_id") or "").strip()
            if not automatic_delivery_type_id:
                raise ValueError(
                    "U7Buy automatic delivery requires a verified automatic_delivery_type_id"
                )
            if str(getattr(subject, "kind", "")) != "stock":
                raise ValueError("U7Buy automatic delivery supports owned stock only")
            credential_bundle = _automatic_delivery_bundle(subject)
            payload["deliveryType"] = automatic_delivery_type_id
            payload["keys"] = [{"encrypted": credential_bundle}]
        else:
            payload["deliveryType"] = str(service.get("delivery_type_id") or U7BUY_MANUAL_DELIVERY_ID)
            payload["deliveryTime"] = str(service.get("delivery_time") or U7BUY_MANUAL_DELIVERY_TIME)
        if platform_id:
            payload["platId"] = str(platform_id)
        region_id = str(service.get("region_id") or "").strip()
        if region_id:
            payload["regionId"] = region_id
        server_id = str(service.get("server_id") or "").strip()
        if server_id:
            payload["serverId"] = server_id
        attributes = service.get("attribute_list")
        if isinstance(attributes, list) and attributes:
            payload["attributeList"] = attributes
        return payload

    def build_bulk_payload(self, subject: Any, listing: ListingDraft, ctx: BuildContext) -> dict[str, Any]:
        return self.build_payload(subject, listing, ctx)


def _redact_subject_credentials(value: str, subject: Any) -> str:
    """Remove exact source credential values from public U7Buy content.

    Titles are rejected when they contain one; descriptions are redacted.  This
    is a last-line guard on top of curated templates: the U7Buy lane is manual
    delivery and must never expose the account credentials at listing time.
    """
    credentials = getattr(subject, "credentials", None)
    if credentials is None:
        return value
    secrets = (
        getattr(credentials, "login", ""),
        getattr(credentials, "password", ""),
        getattr(credentials, "email_login", ""),
        getattr(credentials, "email_password", ""),
        getattr(credentials, "email_login_link", ""),
        getattr(credentials, "security_email", ""),
        getattr(credentials, "security_email_password", ""),
    )
    redacted = value
    for secret in secrets:
        if secret and len(str(secret).strip()) >= 3:
            redacted = redacted.replace(str(secret), "[redacted]")
    return redacted


def _automatic_delivery_bundle(subject: Any) -> str:
    """Return the one private account bundle accepted by U7Buy automatic offers.

    U7Buy's documented request field is named ``encrypted``. Its public API does
    not publish a client-side encryption algorithm or public key, so SDA does not
    invent cryptography. This bundle is sent only to that documented field over
    the authenticated HTTPS API and is removed from local audit representations.
    """
    credentials = getattr(subject, "credentials", None)
    if credentials is None or not getattr(credentials, "login", "") or not getattr(credentials, "password", ""):
        raise ValueError("U7Buy automatic delivery requires a non-empty account login and password")
    bundle = credentials.to_multiline()
    if not bundle.strip():
        raise ValueError("U7Buy automatic delivery requires an account credential bundle")
    return bundle


def sanitize_u7buy_payload_for_audit(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a safe U7Buy payload copy that contains no delivery credential.

    ``keys`` is intentionally removed instead of masked: a mask can still leak
    shape or nested credential fields to logs and database JSON. Durable metadata
    records only that automatic delivery was selected and how many bundles were
    sent.
    """
    safe_payload = deepcopy(payload)
    keys = safe_payload.pop("keys", None)
    if isinstance(keys, list):
        safe_payload["_u7buy_delivery_mode"] = "automatic"
        safe_payload["_u7buy_delivery_key_count"] = len(keys)
    else:
        safe_payload["_u7buy_delivery_mode"] = "manual"
    return safe_payload
