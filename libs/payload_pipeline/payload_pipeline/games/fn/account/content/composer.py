"""Listing composition for resolved Fortnite accounts."""

from __future__ import annotations

from .description_generator import FortniteDescriptionGenerator
from .template_content import build_fortnite_context
from .title_generator import FortniteTitleGenerator
from ..models import FortniteResolvedAccount
from .....content_templates import apply_template_overrides
from .....core import context_keys as ctx
from .....core.contracts import (
    ListingContent,
    ListingDraft,
    MarketplaceListingOverride,
    MediaBundle,
    PipelineRequest,
)

_KNOWN_SEPARATORS = (" | ", " - ", " / ", ", ")


def _smart_truncate(title: str, max_length: int, *, keep_tail: int = 2) -> str:
    """Shorten *title* to *max_length* while preserving the last segments.

    If a known separator (``|``, ``-``, ``/``, ``,``) appears ≥ 2 times the
    title is split on it and middle segments are dropped first.  Otherwise
    the title is trimmed at the last word boundary.
    """
    if len(title) <= max_length:
        return title

    # --- separator-aware path ---
    sep: str | None = None
    for candidate in _KNOWN_SEPARATORS:
        if title.count(candidate) >= 2:
            sep = candidate
            break

    if sep is not None:
        parts = [p.strip() for p in title.split(sep.strip())]
        parts = [p for p in parts if p]  # drop empty

        if len(parts) > keep_tail + 1:
            tail = parts[-keep_tail:]
            head = parts[:-keep_tail]
            tail_str = sep.join(tail)

            kept: list[str] = []
            used = 0
            for part in head:
                added = len(part) + (len(sep) if kept else 0)
                if used + added + len(sep) + len(tail_str) > max_length:
                    break
                kept.append(part)
                used += added

            if kept:
                return sep.join(kept + tail)
            # head couldn't fit at all — just use tail
            return tail_str[:max_length]

    # --- plain word-boundary path ---
    truncated = title[:max_length]
    # don't cut mid-word: find last space
    last_space = truncated.rfind(" ")
    if last_space > max_length // 2:
        truncated = truncated[:last_space]
    return truncated


class FortniteComposer:
    """Generate listing text from the resolved Fortnite account.

    Always builds a full legacy draft first, then overlays any user-created
    templates as per-marketplace overrides.  draft.default is never replaced
    by a template — it remains the legacy fallback for marketplaces without
    a template.
    """

    def __init__(self) -> None:
        self.title_generator = FortniteTitleGenerator()
        self.description_generator = FortniteDescriptionGenerator()

    def compose(
        self,
        account: FortniteResolvedAccount,
        request: PipelineRequest,
        media: MediaBundle,
    ) -> ListingDraft:
        # Manual entries have pre-defined title/description from Google Sheet
        if account.manual_title:
            # Carry the original Imgur album URL so the description generator
            # can include it at the top of the listing description.
            if not media.album_url and account.manual_images:
                media.album_url = account.manual_images

            title = _smart_truncate(account.manual_title, 150)
            g2g_title = _smart_truncate(account.manual_title, 120)
            description = account.manual_description or self.description_generator.generate(
                account, media=media, marketplace="default"
            )
            # Generator adds the album link automatically; manual descriptions bypass
            # the generator so we prepend it here (protocol stripped, all marketplaces).
            if account.manual_description and media.album_url:
                clean_url = media.album_url.removeprefix("https://").removeprefix("http://")
                description = f"Images:\n{clean_url}\n{description}"
        else:
            title = self.title_generator.generate(account, marketplace="default")
            g2g_title = self.title_generator.generate(account, marketplace="g2g")
            description = self.description_generator.generate(
                account, media=media, marketplace="default",
            )

        draft = ListingDraft(
            default=ListingContent(
                title=title,
                description=description,
                tags=["fortnite", "epic-games", "account"],
            ),
            media=media,
            marketplace_overrides={
                "g2g": MarketplaceListingOverride(title=g2g_title),
            },
        )

        # Overlay templates as per-marketplace overrides (draft.default untouched)
        title_templates = ctx.TITLE_TEMPLATES.get(request)
        desc_templates = ctx.DESCRIPTION_TEMPLATES.get(request)
        if title_templates or desc_templates:
            cosmetic_lists = ctx.COSMETIC_LISTS.get(request)
            apply_template_overrides(
                draft,
                build_fortnite_context(
                    account, request, media,
                    cosmetic_lists=cosmetic_lists,
                ),
                title_templates=title_templates,
                description_templates=desc_templates,
            )

        return draft
