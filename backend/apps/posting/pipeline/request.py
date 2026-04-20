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
) -> PipelineRequest:
    """Build a lib PipelineRequest from Django-layer inputs.

    Args:
        game_slug:         Canonical game slug from game_mapp.json (e.g. 'valorant').
        sources:           Raw source dict, e.g. {'lzt': raw_data_dict}.
        kind:              STOCK or DROPSHIPPING.
        disable_media:     Skip media download/upload (True = no IO, faster).
        lzt_image_fetcher: Optional LZT image fetcher for media steps.
    """
    ctx: dict = {ctx_keys.DISABLE_MEDIA: disable_media}
    if lzt_image_fetcher is not None:
        ctx[ctx_keys.LZT_IMAGE_FETCHER] = lzt_image_fetcher

    return PipelineRequest(
        game=game_slug,
        category=ListingCategory.ACCOUNT,
        kind=kind,
        sources=sources,
        context=ctx,
    )
