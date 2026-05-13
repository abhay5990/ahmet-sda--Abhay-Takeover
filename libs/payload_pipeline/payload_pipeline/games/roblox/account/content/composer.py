"""Listing composition for resolved Roblox accounts."""

from __future__ import annotations

from .description_generator import RobloxDescriptionGenerator
from .template_content import build_roblox_context
from .title_generator import RobloxTitleGenerator
from ..models import RobloxResolvedAccount
from .....content_templates import apply_template_overrides
from .....core import context_keys as ctx
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)
from .....core.enums import ListingKind


class RobloxComposer:
    """Generate listing text from the resolved Roblox account.

    Always builds a full legacy draft first, then overlays any user-created
    templates as per-marketplace overrides.  draft.default is never replaced
    by a template — it remains the legacy fallback for marketplaces without
    a template.
    """

    def __init__(self) -> None:
        self.title_generator = RobloxTitleGenerator()
        self.description_generator = RobloxDescriptionGenerator()

    def compose(
        self,
        account: RobloxResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        # Always build legacy draft first
        is_dropshipping = request.kind == ListingKind.DROPSHIPPING
        title = self.title_generator.generate(account, marketplace="default")
        gameboost_title = self.title_generator.generate(account, marketplace="gameboost")
        player_title = self.title_generator.generate(account, marketplace="playerauctions")
        description = self.description_generator.generate(
            account, media=media, marketplace="default", is_dropshipping=is_dropshipping,
        )

        draft = ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["roblox", "account"],
            ),
            media=media,
            marketplace_overrides={
                "gameboost": MarketplaceListingOverride(title=gameboost_title),
                "playerauctions": MarketplaceListingOverride(title=player_title),
            },
        )

        # Overlay templates as per-marketplace overrides (draft.default untouched)
        title_templates = ctx.TITLE_TEMPLATES.get(request)
        desc_templates = ctx.DESCRIPTION_TEMPLATES.get(request)
        if title_templates or desc_templates:
            apply_template_overrides(
                draft,
                build_roblox_context(account, request, media),
                title_templates=title_templates,
                description_templates=desc_templates,
            )

        return draft
