"""Template-backed Roblox listing composition.

This is an opt-in pilot for the generic content template renderer.  The
existing Roblox generators remain the default path.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .....content_templates import (
    JsonFileTemplateProvider,
    TemplateManager,
    TemplateDescriptionGenerator,
    TemplateTitleGenerator,
)
from .....core import context_keys as ctx
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)
from .....core.enums import ListingKind
from ..models import RobloxResolvedAccount


_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "resources" / "content_templates.json"
_TEMPLATE_MANAGER = TemplateManager(JsonFileTemplateProvider(_TEMPLATE_PATH))


class RobloxTemplateContentGenerator:
    """Compose Roblox listing content using structured templates."""

    def __init__(self) -> None:
        self.title_generator = TemplateTitleGenerator()
        self.description_generator = TemplateDescriptionGenerator()

    def compose(
        self,
        account: RobloxResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        templates = _template_map(request)
        context = _build_context(account, request, media)

        default_template = templates["default"]
        title = self.title_generator.generate(default_template["title"], context)
        description = self.description_generator.generate(default_template["description"], context)

        overrides: dict[str, MarketplaceListingOverride] = {}
        for marketplace, marketplace_template in templates.items():
            if marketplace == "default":
                continue
            title_template = marketplace_template.get("title")
            description_template = marketplace_template.get("description")
            if title_template or description_template:
                overrides[marketplace.lower()] = MarketplaceListingOverride(
                    title=(
                        self.title_generator.generate(title_template, context)
                        if title_template
                        else None
                    ),
                    description=(
                        self.description_generator.generate(description_template, context)
                        if description_template
                        else None
                    ),
                )

        return ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["roblox", "account"],
            ),
            media=media,
            marketplace_overrides=overrides,
        )


def _template_map(request: PipelineRequest) -> dict[str, dict[str, Any]]:
    manager = ctx.CONTENT_TEMPLATE_MANAGER.get(request) or _TEMPLATE_MANAGER
    overrides = ctx.CONTENT_TEMPLATE_OVERRIDES.get(request, {})
    return manager.load(overrides=overrides)


def _build_context(
    account: RobloxResolvedAccount,
    request: PipelineRequest,
    media: MediaBundle,
) -> dict[str, Any]:
    context = {
        field.name: getattr(account, field.name)
        for field in fields(account)
        if field.name != "credentials"
    }
    context.update({
        "username": account.username or "Unknown",
        "roblox_id": account.roblox_id,
        "profile_url": (
            f"https://www.roblox.com/users/{account.roblox_id}/profile"
            if account.roblox_id
            else "N/A"
        ),
        "robux": account.robux,
        "incoming_robux_total": account.incoming_robux_total,
        "inventory_price": account.inventory_price,
        "inventory_price_int": int(account.inventory_price),
        "ugc_limited_price": account.ugc_limited_price,
        "ugc_limited_price_int": int(account.ugc_limited_price),
        "game_pass_total_robux": account.game_pass_total_robux,
        "offsale_count": account.offsale_count,
        "age_verified": account.age_verified,
        "age_verified_label": "Yes" if account.age_verified else "No",
        "register_date": _format_register_date(account.register_date),
        "register_year": _register_year(account.register_date),
        "letter_tag": _letter_tag(account.username),
        "letter_label": _letter_label(account.username),
        "album_url": media.album_url or "",
        "is_stock": request.kind == ListingKind.STOCK,
    })
    return context


def _letter_tag(username: str) -> str:
    if username and len(username) == 3:
        return "3 Letter, "
    if username and len(username) == 4:
        return "4 Letter, "
    return ""


def _letter_label(username: str) -> str:
    if username and len(username) == 3:
        return "3 Letter"
    if username and len(username) == 4:
        return "4 Letter"
    return ""


def _format_register_date(timestamp: int) -> str:
    try:
        return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return "Unknown"


def _register_year(timestamp: int) -> str:
    try:
        return str(datetime.fromtimestamp(int(timestamp), tz=timezone.utc).year)
    except Exception:
        return "Unknown"
