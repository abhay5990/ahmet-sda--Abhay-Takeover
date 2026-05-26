"""Helpers for canonical Listing.variant slugs.

Posting may select one dimension explicitly (usually ``platform``) while the
resolved account supplies another fixed dimension (usually ``region``). These
helpers build the persisted Listing.variant value from both sources.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

COMPONENT_ORDER = ('region', 'platform')

_SUBJECT_ATTRS = {
    'region': ('region', 'region_phrase', 'server'),
    'platform': ('main_platform', 'primary_linkable_platform', 'platform'),
}


def build_composite_variant(
    components: Mapping[str, str] | None,
    *,
    variant_ctx: dict[str, Any] | None = None,
) -> str:
    """Return an ordered composite slug from variant component slugs."""
    if not components:
        return ''

    parts: list[str] = []
    for variant_type in _component_order(variant_ctx, components):
        slug = str(components.get(variant_type) or '').strip().lower()
        if slug and slug != 'auto':
            parts.append(slug)
    return '-'.join(parts)


def resolve_listing_variant_slug(
    *,
    subject: Any,
    variant_ctx: dict[str, Any] | None,
    selected_variants: Mapping[str, str] | None = None,
    fallback: str = '',
) -> str:
    """Resolve the slug that should be persisted to Listing.variant.

    ``selected_variants`` wins for dimensions chosen by the router. Missing
    dimensions are resolved from the prepared subject through ``variant_ctx``.
    """
    components: dict[str, str] = {}

    for variant_type in _component_order(variant_ctx, selected_variants):
        selected = str((selected_variants or {}).get(variant_type) or '').strip()
        if selected and selected.lower() != 'auto':
            components[variant_type] = selected
            continue

        slug = _resolve_subject_slug(subject, variant_ctx, variant_type)
        if slug:
            components[variant_type] = slug

    return build_composite_variant(
        components, variant_ctx=variant_ctx,
    ) or fallback


def variant_value_contains_slug(
    value: str | None,
    slug: str,
    *,
    known_slugs: Collection[str] | None = None,
) -> bool:
    """Return True when a persisted variant contains a component slug."""
    value = str(value or '').strip().lower()
    slug = str(slug or '').strip().lower()
    if not value or not slug:
        return False
    if value == slug:
        return True
    if known_slugs:
        known_set = {str(item).lower() for item in known_slugs if item}
        if value in known_set:
            return False
        components = _split_known_components(value, known_set)
        if components:
            return slug in components
    return (
        value.startswith(f'{slug}-')
        or value.endswith(f'-{slug}')
        or f'-{slug}-' in value
    )


def _split_known_components(
    value: str,
    known_slugs: Collection[str],
) -> list[str]:
    known_set = {str(item).lower() for item in known_slugs if item}
    ordered_slugs = sorted(
        known_set,
        key=len,
        reverse=True,
    )
    memo: dict[str, list[str] | None] = {}

    def _walk(remainder: str) -> list[str] | None:
        if remainder in memo:
            return memo[remainder]
        if remainder in known_set:
            memo[remainder] = [remainder]
            return memo[remainder]

        for candidate in ordered_slugs:
            prefix = f'{candidate}-'
            if not remainder.startswith(prefix):
                continue
            tail = remainder[len(prefix):]
            tail_parts = _walk(tail)
            if tail_parts:
                memo[remainder] = [candidate, *tail_parts]
                return memo[remainder]

        memo[remainder] = None
        return None

    return _walk(value) or []


def _component_order(
    variant_ctx: dict[str, Any] | None,
    components: Mapping[str, str] | None,
) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []

    for variant_type in COMPONENT_ORDER:
        if _has_component(variant_type, variant_ctx, components):
            ordered.append(variant_type)
            seen.add(variant_type)

    for source in (variant_ctx or {}, components or {}):
        for variant_type in source:
            if variant_type not in seen:
                ordered.append(variant_type)
                seen.add(variant_type)

    return ordered


def _has_component(
    variant_type: str,
    variant_ctx: dict[str, Any] | None,
    components: Mapping[str, str] | None,
) -> bool:
    return (
        variant_type in (variant_ctx or {})
        or bool((components or {}).get(variant_type))
    )


def _resolve_subject_slug(
    subject: Any,
    variant_ctx: dict[str, Any] | None,
    variant_type: str,
) -> str:
    if not variant_ctx:
        return ''

    for attr in _SUBJECT_ATTRS.get(variant_type, (variant_type,)):
        value = str(getattr(subject, attr, '') or '').strip()
        if not value:
            continue
        entry = _lookup_variant_entry(variant_ctx, variant_type, value)
        if entry:
            return str(entry.get('slug') or '').strip()
    return ''


def _lookup_variant_entry(
    variant_ctx: dict[str, Any],
    variant_type: str,
    key: str,
) -> dict[str, Any] | None:
    type_map = variant_ctx.get(variant_type) or {}
    if key in type_map:
        return type_map[key]

    key_lower = key.lower()
    for candidate, entry in type_map.items():
        if str(candidate).lower() == key_lower:
            return entry
        if str(entry.get('slug') or '').lower() == key_lower:
            return entry
    return None
