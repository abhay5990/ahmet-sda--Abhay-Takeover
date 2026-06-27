"""Registry for game slices and marketplace builders."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic

from .contracts import (
    ListingComposer,
    MediaStrategy,
    PayloadBuilder,
    SubjectResolver,
    TSubject,
)
from .capabilities import MediaCapabilities, OVERRIDE_ONLY
from .enums import ListingCategory
from .exceptions import RegistryConflictError, RegistryLookupError


@dataclass(slots=True)
class GameDefinition(Generic[TSubject]):
    """Everything required to process one game + category slice."""

    game: str
    resolver: SubjectResolver[TSubject]
    composer: ListingComposer[TSubject]
    category: ListingCategory = ListingCategory.ACCOUNT
    marketplaces: dict[str, PayloadBuilder[TSubject]] = field(default_factory=dict)
    media_strategy: MediaStrategy[TSubject] | None = None

    @property
    def registry_key(self) -> str:
        return f"{self.game.lower()}:{self.category.lower()}"

    def get_builder(self, marketplace: str) -> PayloadBuilder[TSubject]:
        builder = self.marketplaces.get(marketplace.lower())
        if builder is None:
            raise RegistryLookupError(
                "Marketplace "
                f"'{marketplace}' is not registered for game '{self.game}' "
                f"and category '{self.category}'."
            )
        return builder


class PipelineRegistry:
    """Mutable registry used by the new orchestrator."""

    def __init__(self) -> None:
        self._definitions: dict[str, GameDefinition[Any]] = {}

    def register_game(self, definition: GameDefinition[Any], *, overwrite: bool = False) -> None:
        key = definition.registry_key
        if key in self._definitions and not overwrite:
            raise RegistryConflictError(
                f"Game slice '{key}' is already registered. "
                "Pass overwrite=True to replace it."
            )
        self._definitions[key] = definition

    def get_game(self, game: str, category: ListingCategory = ListingCategory.ACCOUNT) -> GameDefinition[Any]:
        key = self._make_key(game, category)
        definition = self._definitions.get(key)
        if definition is None:
            raise RegistryLookupError(f"Game slice '{key}' is not registered.")
        return definition

    def has_game(self, game: str, category: ListingCategory = ListingCategory.ACCOUNT) -> bool:
        return self._make_key(game, category) in self._definitions

    def list_games(self) -> list[str]:
        return sorted(self._definitions.keys())

    def get_media_capabilities(
        self,
        game: str,
        category: ListingCategory = ListingCategory.ACCOUNT,
    ) -> MediaCapabilities:
        """Return media capabilities for a registered game slice.

        Falls back to ``OVERRIDE_ONLY`` when the strategy does not
        declare a ``capabilities`` attribute.
        """
        definition = self._definitions.get(self._make_key(game, category))
        if definition is None or definition.media_strategy is None:
            return OVERRIDE_ONLY

        return getattr(definition.media_strategy, "capabilities", OVERRIDE_ONLY)

    def _make_key(self, game: str, category: ListingCategory) -> str:
        return f"{game.lower()}:{category.lower()}"
