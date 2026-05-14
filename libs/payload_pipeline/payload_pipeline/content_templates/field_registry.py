"""Public API for template field metadata and sample context.

Consumers (e.g. the Django template editor) import only these functions.
All introspection of resolved models stays encapsulated here.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from dataclasses import is_dataclass
from functools import lru_cache
from typing import Any, get_type_hints

from ..core.contracts import FieldMeta, ResolvedAccountBase
from ..core.enums import ListingCategory
from ..core.exceptions import RegistryLookupError

logger = logging.getLogger(__name__)

# Module-level cached registry to avoid rebuilding on every call.
_default_registry = None


def get_field_registry(
    game_slug: str,
    category: str = "account",
) -> list[dict[str, Any]]:
    """Return field metadata for the template editor UI.

    Each entry contains ``name``, ``placeholder``, ``description``,
    ``sample``, and ``source`` keys.
    """
    model = _resolve_model(game_slug, category)
    result: list[dict[str, Any]] = []

    for name, meta in model.FIELD_META.items():
        result.append(_meta_to_dict(name, meta))

    for name, meta in model.COMPUTED_FIELDS.items():
        result.append(_meta_to_dict(name, meta))

    return result


def get_available_fields(
    game_slug: str,
    category: str = "account",
) -> set[str]:
    """Return the set of valid field names for a game model.

    Used by validation to check template placeholders.
    """
    model = _resolve_model(game_slug, category)
    return set(model.FIELD_META) | set(model.COMPUTED_FIELDS)


def get_sample_context(
    game_slug: str,
    category: str = "account",
) -> dict[str, Any]:
    """Return a sample context dict suitable for template preview rendering."""
    model = _resolve_model(game_slug, category)
    context: dict[str, Any] = {
        name: meta.sample for name, meta in model.FIELD_META.items()
    }
    context.update({
        name: meta.sample for name, meta in model.COMPUTED_FIELDS.items()
    })
    return context


def get_resolved_model_name(
    game_slug: str,
    category: str = "account",
) -> str:
    """Return the resolved model class name (e.g. ``'RobloxResolvedAccount'``)."""
    model = _resolve_model(game_slug, category)
    return model.__name__


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _meta_to_dict(name: str, meta: FieldMeta) -> dict[str, Any]:
    return {
        "name": name,
        "placeholder": "{" + name + "}",
        "description": meta.description,
        "sample": _format_sample(meta.sample),
        "source": meta.source,
        "field_type": _infer_field_type(meta.sample),
    }


def _infer_field_type(sample: Any) -> str:
    """Infer a simple type label from a sample value for the UI."""
    if isinstance(sample, bool):
        return "bool"
    if isinstance(sample, int):
        return "int"
    if isinstance(sample, float):
        return "float"
    if isinstance(sample, list):
        return "list"
    return "str"


def _format_sample(value: Any) -> str:
    """Convert a sample value to a human-readable display string."""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value[:5])
    return str(value)


def _get_default_registry():
    """Return a cached pipeline registry instance."""
    global _default_registry
    if _default_registry is None:
        from .. import build_default_registry
        _default_registry = build_default_registry()
    return _default_registry


@lru_cache(maxsize=64)
def _resolve_model(
    game_slug: str,
    category: str = "account",
) -> type[ResolvedAccountBase]:
    """Look up the resolved model class for a game slug.

    Uses the pipeline registry to find the resolver, then inspects
    return-type annotations or sibling ``models`` module.
    Falls back to ``ResolvedAccountBase`` when resolution fails.
    """
    if not game_slug:
        return ResolvedAccountBase

    try:
        registry = _get_default_registry()
        listing_category = _to_listing_category(category)
        definition = registry.get_game(game_slug, listing_category)
    except (KeyError, ValueError, RegistryLookupError) as exc:
        logger.warning("Failed to resolve model for %s/%s: %s", game_slug, category, exc)
        return ResolvedAccountBase
    except ImportError as exc:
        logger.error("Import error resolving model for %s: %s", game_slug, exc)
        return ResolvedAccountBase

    model = _model_from_resolver_return_type(definition.resolver)
    if model is not None:
        return model

    model = _model_from_resolver_module(definition.resolver.__class__.__module__)
    if model is not None:
        return model

    logger.warning("Could not find resolved model for %s/%s, using base", game_slug, category)
    return ResolvedAccountBase


def _to_listing_category(value: str) -> ListingCategory:
    try:
        return ListingCategory(value or "account")
    except ValueError:
        return ListingCategory.ACCOUNT


def _model_from_resolver_return_type(resolver: Any) -> type[ResolvedAccountBase] | None:
    try:
        return_type = get_type_hints(resolver.resolve).get("return")
    except (TypeError, AttributeError, NameError):
        return None
    return return_type if _is_resolved_model(return_type) else None


def _model_from_resolver_module(module_name: str) -> type[ResolvedAccountBase] | None:
    package = module_name.rsplit(".", 1)[0]
    try:
        module = importlib.import_module(f"{package}.models")
    except ImportError:
        return None

    for _, cls in inspect.getmembers(module, inspect.isclass):
        if _is_resolved_model(cls):
            return cls
    return None


def _is_resolved_model(value: Any) -> bool:
    return (
        inspect.isclass(value)
        and value is not ResolvedAccountBase
        and issubclass(value, ResolvedAccountBase)
        and is_dataclass(value)
    )
