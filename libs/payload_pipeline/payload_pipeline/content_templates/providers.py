"""Template provider abstractions for structured listing content."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .validation import TemplateValidationError, validate_template_map


TemplateMap = dict[str, dict[str, Any]]


class TemplateProvider(Protocol):
    """Load a validated marketplace-keyed template map."""

    def load(self) -> TemplateMap:
        ...


class TemplateOverrideProvider(Protocol):
    """Load partial marketplace-keyed template overrides."""

    def load_overrides(self) -> Mapping[str, Any]:
        ...


@dataclass(slots=True)
class DictTemplateProvider:
    """Load templates from an in-memory dict."""

    templates: Mapping[str, Any]

    def load(self) -> TemplateMap:
        data = _to_template_map(deepcopy(dict(self.templates)))
        validate_template_map(data)
        return data


@dataclass(slots=True)
class DictTemplateOverrideProvider:
    """Load partial template overrides from an in-memory dict."""

    overrides: Mapping[str, Any]

    def load_overrides(self) -> Mapping[str, Any]:
        return deepcopy(dict(self.overrides))


@dataclass(slots=True)
class JsonFileTemplateProvider:
    """Load templates from a JSON file."""

    path: str | Path

    def load(self) -> TemplateMap:
        path = Path(self.path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        data = _to_template_map(raw)
        validate_template_map(data)
        return data


@dataclass(slots=True)
class JsonFileTemplateOverrideProvider:
    """Load partial template overrides from a JSON file."""

    path: str | Path

    def load_overrides(self) -> Mapping[str, Any]:
        path = Path(self.path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise TemplateValidationError("template override map must be an object")
        return _to_template_map(raw)


def merge_template_maps(base: Mapping[str, Any], overrides: Mapping[str, Any]) -> TemplateMap:
    """Return a validated shallow marketplace/template merge.

    Override values replace complete ``title`` or ``description`` specs within
    a marketplace entry.  They do not deep-merge individual ``parts`` or
    ``blocks`` lists, which keeps UI/DB updates predictable.
    """
    if not isinstance(overrides, Mapping):
        raise TemplateValidationError("template override map must be an object")

    merged = _to_template_map(deepcopy(dict(base)))
    for marketplace, override in overrides.items():
        if not isinstance(marketplace, str) or not isinstance(override, Mapping):
            continue
        current = dict(merged.get(marketplace, {}))
        for key in ("title", "description"):
            if key in override:
                current[key] = deepcopy(override[key])
        merged[marketplace] = current
    validate_template_map(merged)
    return merged


def _to_template_map(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return raw
    return {
        str(name): dict(template) if isinstance(template, Mapping) else template
        for name, template in raw.items()
    }
