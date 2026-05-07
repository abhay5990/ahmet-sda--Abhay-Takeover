"""Template manager for default templates plus external overrides."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .providers import TemplateMap, TemplateOverrideProvider, TemplateProvider, merge_template_maps


@dataclass(slots=True)
class TemplateManager:
    """Load templates from a default provider and optional override providers.

    A game slice can keep its bundled JSON templates as the default provider,
    while the backend supplies DB-backed partial overrides through
    ``override_provider`` or request-scoped ``overrides``.
    """

    default_provider: TemplateProvider
    override_provider: TemplateOverrideProvider | None = None
    cache_defaults: bool = True
    _cached_defaults: TemplateMap | None = field(default=None, init=False, repr=False)

    def load(self, overrides: Mapping[str, Any] | None = None) -> TemplateMap:
        templates = self._load_defaults()

        if self.override_provider is not None:
            provider_overrides = self.override_provider.load_overrides()
            if provider_overrides:
                templates = merge_template_maps(templates, provider_overrides)

        if overrides:
            templates = merge_template_maps(templates, overrides)

        return templates

    def _load_defaults(self) -> TemplateMap:
        if self.cache_defaults and self._cached_defaults is not None:
            return deepcopy(self._cached_defaults)

        loaded = self.default_provider.load()
        if self.cache_defaults:
            self._cached_defaults = deepcopy(loaded)
        return deepcopy(loaded)
