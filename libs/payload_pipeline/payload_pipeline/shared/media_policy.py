"""Media source selection helpers."""

from __future__ import annotations

from enum import Enum

from ..core import context_keys as ctx
from ..core.contracts import PipelineRequest
from ..core.enums import ListingKind


class MediaSource(str, Enum):
    """Concrete media sources a strategy can try."""

    LZT = "lzt"
    GENERATED = "generated"


class MediaSourcePolicy(str, Enum):
    """How media strategies should choose between LZT and generated media."""

    LZT = "lzt"
    GENERATED = "generated"
    LZT_FIRST = "lzt_first"
    GENERATED_FIRST = "generated_first"
    AUTO = "auto"


_POLICY_ALIASES = {
    "lzt": MediaSourcePolicy.LZT,
    "lolz": MediaSourcePolicy.LZT,
    "lolzteam": MediaSourcePolicy.LZT,
    "generated": MediaSourcePolicy.GENERATED,
    "generate": MediaSourcePolicy.GENERATED,
    "local": MediaSourcePolicy.GENERATED,
    "lzt_first": MediaSourcePolicy.LZT_FIRST,
    "lolz_first": MediaSourcePolicy.LZT_FIRST,
    "lolzteam_first": MediaSourcePolicy.LZT_FIRST,
    "generated_first": MediaSourcePolicy.GENERATED_FIRST,
    "generate_first": MediaSourcePolicy.GENERATED_FIRST,
    "local_first": MediaSourcePolicy.GENERATED_FIRST,
    "auto": MediaSourcePolicy.AUTO,
}


def resolve_media_source_policy(request: PipelineRequest) -> MediaSourcePolicy:
    """Return the effective media source policy for a request."""
    raw = request.context.get(ctx.MEDIA_SOURCE_POLICY)
    if raw is None or raw == "":
        return default_media_source_policy(request)

    normalized = str(raw).strip().lower().replace("-", "_")
    policy = _POLICY_ALIASES.get(normalized)
    if policy is None or policy is MediaSourcePolicy.AUTO:
        return default_media_source_policy(request)
    return policy


def default_media_source_policy(request: PipelineRequest) -> MediaSourcePolicy:
    """Use cheap LZT media for stock and controlled generation for dropshipping."""
    if request.kind == ListingKind.DROPSHIPPING:
        return MediaSourcePolicy.GENERATED_FIRST
    return MediaSourcePolicy.LZT_FIRST


def media_source_order(request: PipelineRequest) -> tuple[MediaSource, ...]:
    """Return the ordered concrete sources a media strategy should try."""
    policy = resolve_media_source_policy(request)
    if policy is MediaSourcePolicy.LZT:
        return (MediaSource.LZT,)
    if policy is MediaSourcePolicy.GENERATED:
        return (MediaSource.GENERATED,)
    if policy is MediaSourcePolicy.GENERATED_FIRST:
        return (MediaSource.GENERATED, MediaSource.LZT)
    return (MediaSource.LZT, MediaSource.GENERATED)
