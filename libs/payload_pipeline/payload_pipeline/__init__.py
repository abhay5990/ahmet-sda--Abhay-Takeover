"""Foundational payload pipeline package for the next game listing architecture."""

from .core.pipeline import PayloadPipeline
from .core.registry import PipelineRegistry
from .games import (
    register_default_games,
    register_experimental_games,
    register_supported_games,
)


def build_default_registry() -> PipelineRegistry:
    """Create a registry with only production-ready (supported) games.

    Supported means the slice has at least one marketplace builder and can
    produce end-to-end payloads.  Currently all 13 slices are supported.

    Use ``build_full_registry()`` to include experimental slices as well
    (currently identical since no experimental slices remain).
    """
    registry = PipelineRegistry()
    register_default_games(registry)
    return registry


def build_full_registry() -> PipelineRegistry:
    """Create a registry with all games including experimental/incomplete slices.

    Currently equivalent to ``build_default_registry()`` since all slices
    have been promoted to supported.  The experimental entry point is
    preserved for future use.
    """
    registry = PipelineRegistry()
    register_supported_games(registry)
    register_experimental_games(registry)
    return registry


__all__ = [
    "PayloadPipeline",
    "PipelineRegistry",
    "build_default_registry",
    "build_full_registry",
]
