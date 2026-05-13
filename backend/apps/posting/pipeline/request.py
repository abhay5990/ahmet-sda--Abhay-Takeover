"""PipelineRequest factory — bridges Django models to the payload_pipeline lib."""

from __future__ import annotations

from payload_pipeline.core import context_keys as ctx_keys
from payload_pipeline.core.contracts import ListingCategory, ListingKind, PipelineRequest


def build_request(
    *,
    game_slug: str,
    sources: dict,
    kind: ListingKind,
    disable_media: bool = True,
    lzt_image_fetcher=None,
    title_templates: dict[str, str] | None = None,
    description_templates: dict[str, str] | None = None,
) -> PipelineRequest:
    """Build a lib PipelineRequest from Django-layer inputs.

    Args:
        game_slug:             Canonical game slug (e.g. 'valorant').
        sources:               Raw source dict, e.g. {'lzt': raw_data_dict}.
        kind:                  STOCK or DROPSHIPPING.
        disable_media:         Skip media download/upload.
        lzt_image_fetcher:     Optional LZT image fetcher for media steps.
        title_templates:       Marketplace→body mapping for title templates.
        description_templates: Same for description templates.
    """
    ctx: dict = {ctx_keys.DISABLE_MEDIA: disable_media}
    if lzt_image_fetcher is not None:
        ctx[ctx_keys.LZT_IMAGE_FETCHER] = lzt_image_fetcher
    if title_templates:
        ctx[ctx_keys.TITLE_TEMPLATES] = title_templates
    if description_templates:
        ctx[ctx_keys.DESCRIPTION_TEMPLATES] = description_templates

    return PipelineRequest(
        game=game_slug,
        category=ListingCategory.ACCOUNT,
        kind=kind,
        sources=sources,
        context=ctx,
    )
