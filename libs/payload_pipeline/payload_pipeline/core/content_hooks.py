"""Shared content post-processing hooks for composers."""

from __future__ import annotations

from . import context_keys as ctx
from .config import is_feature_enabled
from .contracts import PipelineRequest


def prefix_ref_key(description: str, request: PipelineRequest) -> str:
    """Prepend ref_key to description if the feature is enabled.

    Returns the description unchanged when the feature is off or no ref_key
    is present in the request context.
    """
    if not is_feature_enabled("ref_key_in_description"):
        return description

    ref_key = ctx.REF_KEY.get(request, "")
    if not ref_key:
        return description

    return f"{ref_key}\n{description}"
