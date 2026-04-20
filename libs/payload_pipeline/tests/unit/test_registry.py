"""Tests for registry support classification (Phase 3.1).

Validates that the default registry contains only supported slices
(those with at least one marketplace builder) and that experimental
slices require explicit opt-in.
"""

from __future__ import annotations

import pytest

from payload_pipeline import (
    build_default_registry,
    build_full_registry,
)
from payload_pipeline.games import (
    register_experimental_games,
    register_supported_games,
)
from payload_pipeline.core.registry import PipelineRegistry

# -- Classification constants ------------------------------------------------

SUPPORTED_GAMES = [
    "rainbow-six-siege",
    "counter-strike-2",
    "valorant",
    "brawl-stars",
    "clash-of-clans",
    "clash-royale",
    "fortnite",
    "genshin-impact",
    "grand-theft-auto-5",
    "league-of-legends",
    "roblox",
    "steam",
    "ubisoft-connect",
]

EXPERIMENTAL_GAMES: list[str] = [
    # Currently empty — all slices have been promoted to supported.
]


# -- Default registry tests --------------------------------------------------

class TestDefaultRegistry:
    """build_default_registry() should only contain supported slices."""

    @pytest.fixture(autouse=True)
    def setup_registry(self):
        self.registry = build_default_registry()

    @pytest.mark.parametrize("game", SUPPORTED_GAMES)
    def test_supported_game_is_registered(self, game: str):
        assert self.registry.has_game(game), (
            f"Supported game '{game}' should be in default registry"
        )

    def test_experimental_games_excluded(self):
        """Experimental games should NOT appear in the default registry."""
        for game in EXPERIMENTAL_GAMES:
            assert not self.registry.has_game(game), (
                f"Experimental game '{game}' should NOT be in default registry"
            )

    def test_supported_slices_have_builders(self):
        """Every slice in default registry must have at least one marketplace builder."""
        for key in self.registry.list_games():
            game, kind = key.split(":")
            definition = self.registry.get_game(game, kind)
            assert definition.marketplaces, (
                f"Slice '{key}' in default registry has no marketplace builders"
            )


# -- Full registry tests ------------------------------------------------------

class TestFullRegistry:
    """build_full_registry() should contain both supported and experimental slices."""

    @pytest.fixture(autouse=True)
    def setup_registry(self):
        self.registry = build_full_registry()

    @pytest.mark.parametrize("game", SUPPORTED_GAMES)
    def test_supported_game_is_registered(self, game: str):
        assert self.registry.has_game(game)

    def test_experimental_games_included(self):
        """Experimental games should appear in the full registry."""
        for game in EXPERIMENTAL_GAMES:
            assert self.registry.has_game(game), (
                f"Experimental game '{game}' should be in full registry"
            )

    def test_full_registry_equals_default_when_no_experimental(self):
        """When experimental set is empty, full and default registries should match."""
        if EXPERIMENTAL_GAMES:
            pytest.skip("Only relevant when no experimental slices exist")
        default = build_default_registry()
        assert sorted(self.registry.list_games()) == sorted(default.list_games())


# -- Registration function tests ---------------------------------------------

class TestRegistrationFunctions:
    """Individual registration functions work correctly."""

    def test_register_supported_only(self):
        registry = PipelineRegistry()
        register_supported_games(registry)

        for game in SUPPORTED_GAMES:
            assert registry.has_game(game)
        for game in EXPERIMENTAL_GAMES:
            assert not registry.has_game(game)

    def test_register_experimental_only(self):
        registry = PipelineRegistry()
        register_experimental_games(registry)

        for game in EXPERIMENTAL_GAMES:
            assert registry.has_game(game)
        # When experimental is empty, the registry should be empty
        if not EXPERIMENTAL_GAMES:
            assert len(registry.list_games()) == 0

    def test_no_duplicate_registration(self):
        """Registering supported + experimental should not conflict."""
        registry = PipelineRegistry()
        register_supported_games(registry)
        register_experimental_games(registry)

        all_games = SUPPORTED_GAMES + EXPERIMENTAL_GAMES
        assert len(registry.list_games()) == len(all_games)

    def test_default_equals_supported(self):
        """build_default_registry() should produce the same set as register_supported_games()."""
        default = build_default_registry()
        supported = PipelineRegistry()
        register_supported_games(supported)

        assert sorted(default.list_games()) == sorted(supported.list_games())
