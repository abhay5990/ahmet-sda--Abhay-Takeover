"""Credential spec resolution chain.

Resolves the appropriate CredentialSpec for a pool or game+variant combination.
Falls back through: explicit pool spec → variant spec → game default → code preset.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db.models import Q

if TYPE_CHECKING:
    from apps.posting.models import CredentialSpec, OfferPool

from .presets import (
    ROLE_TO_OWNED_PRODUCT_FIELD,
    CredentialFieldSchema,
    get_preset,
)

logger = logging.getLogger(__name__)


# ── Variant Lookup ───────────────────────────────────────────────


def variant_value_contains_slug(
    value: str,
    candidate_slug: str,
    known_slugs: set[str] | None = None,
) -> bool:
    """Check if a composite variant value (e.g. 'eu-psn') contains a slug component.

    Splits on '-' and checks if candidate_slug appears as a component,
    but only if it's not ambiguous with other known slugs.
    """
    value_lower = value.lower()
    slug_lower = candidate_slug.lower()

    # Direct containment as hyphen-separated component
    parts = value_lower.split("-")
    if slug_lower in parts:
        return True

    # Multi-part slug check: e.g. "pc-legacy" in "eu-pc-legacy"
    if slug_lower in value_lower:
        # Verify it's a component boundary match
        idx = value_lower.find(slug_lower)
        before_ok = idx == 0 or value_lower[idx - 1] == "-"
        after_ok = (idx + len(slug_lower) >= len(value_lower)) or value_lower[idx + len(slug_lower)] == "-"
        if before_ok and after_ok:
            return True

    return False


def resolve_game_variant(game, value: str | None):
    """Resolve a variant string to a GameVariant instance.

    Tries exact match on slug/label/source_key, then composite fallback.
    Returns GameVariant or None.
    """
    from apps.posting.models import GameVariant

    value = str(value or "").strip()
    if not value:
        return None

    # Exact slug/label/source_key match (case-insensitive)
    variant = GameVariant.objects.filter(game=game).filter(
        Q(slug__iexact=value)
        | Q(label__iexact=value)
        | Q(source_key__iexact=value)
    ).first()
    if variant:
        return variant

    # Composite value fallback: eu-psn, na-pc, etc.
    variants = list(GameVariant.objects.filter(game=game))
    known_slugs = {v.slug.lower() for v in variants}
    for candidate in variants:
        if variant_value_contains_slug(value, candidate.slug, known_slugs=known_slugs):
            return candidate

    return None


# ── Spec Resolution ──────────────────────────────────────────────


def resolve_spec(pool: OfferPool) -> CredentialSpec | None:
    """Resolve the credential spec for a pool using the full chain.

    1. pool.credential_spec (if active)
    2. pool.credential_spec inactive → log warning, don't use
    3. Variant-level spec from pool.listing.variant
    4. Game-level default spec
    5. Code-level preset (returns None; caller uses preset directly)
    """
    # 1-2: Explicit pool spec
    if pool.credential_spec_id:
        spec = pool.credential_spec
        if spec and spec.is_active:
            return spec
        logger.warning(
            "Pool #%d has inactive credential_spec #%d — falling back to resolver chain",
            pool.pk,
            pool.credential_spec_id,
        )

    # 3-4: Resolve from game + variant
    game = pool.game
    variant_value = getattr(pool.listing, "variant", None) if pool.listing else None
    return resolve_spec_for_game_variant(game, variant_value)


def resolve_spec_for_game_variant(game, variant_value: str | None) -> CredentialSpec | None:
    """Resolve a CredentialSpec from game + variant string.

    1. Find GameVariant from variant_value
    2. Look up variant-level active spec
    3. Fall back to game-level default active spec
    4. Return None (caller should use code-level preset)
    """
    from apps.posting.models import CredentialSpec

    variant = resolve_game_variant(game, variant_value) if variant_value else None

    if variant:
        spec = CredentialSpec.objects.filter(
            variant=variant,
            is_active=True,
        ).first()
        if spec:
            return spec

    # Game-level default (variant=NULL)
    spec = CredentialSpec.objects.filter(
        game=game,
        variant__isnull=True,
        is_active=True,
    ).first()
    if spec:
        return spec

    return None


# ── Public Helpers ───────────────────────────────────────────────


def resolve_fields(pool: OfferPool) -> list[dict]:
    """Resolve credential fields for a pool.

    Returns list of field dicts from spec or code-level preset.
    """
    spec = resolve_spec(pool)
    if spec:
        return spec.fields

    game_slug = pool.game.slug if pool.game else ""
    variant_value = getattr(pool.listing, "variant", None) if pool.listing else None
    variant_obj = resolve_game_variant(pool.game, variant_value) if variant_value and pool.game else None
    variant_slug = variant_obj.slug if variant_obj else None

    preset = get_preset(game_slug, variant_slug)
    if preset:
        return preset[1]

    # Ultimate fallback
    from .presets import _generic_fields
    return _generic_fields()


def resolve_format_template(
    pool: OfferPool,
    marketplace: str,
) -> str | dict | None:
    """Resolve the format template for a pool + marketplace.

    Returns template string/dict or None.
    """
    spec = resolve_spec(pool)
    if spec and spec.format_templates:
        return spec.format_templates.get(marketplace)

    game_slug = pool.game.slug if pool.game else ""
    variant_value = getattr(pool.listing, "variant", None) if pool.listing else None
    variant_obj = resolve_game_variant(pool.game, variant_value) if variant_value and pool.game else None
    variant_slug = variant_obj.slug if variant_obj else None

    preset = get_preset(game_slug, variant_slug)
    if preset:
        return preset[2].get(marketplace)

    return None


def build_field_role_map(spec_or_fields) -> dict[str, str]:
    """Build a mapping from role -> field key.

    Args:
        spec_or_fields: CredentialSpec instance or list of field dicts.

    Returns:
        Dict like {"login": "psn_id", "password": "psn_pass", "email": "email", ...}
    """
    if hasattr(spec_or_fields, "fields"):
        fields = spec_or_fields.fields
    else:
        fields = spec_or_fields

    role_map: dict[str, str] = {}
    for field in fields:
        if isinstance(field, dict):
            role = field.get("role", "extra")
            key = field.get("key", "")
        elif isinstance(field, CredentialFieldSchema):
            role = field.role
            key = field.key
        else:
            continue

        if role != "extra":
            role_map[role] = key
        # For extras, we don't put them in role_map (they're looked up by key)

    return role_map


def build_reverse_role_map(spec_or_fields) -> dict[str, str]:
    """Build a mapping from field key -> role.

    Returns dict like {"psn_id": "login", "psn_pass": "password", "dob": "extra", ...}
    """
    if hasattr(spec_or_fields, "fields"):
        fields = spec_or_fields.fields
    else:
        fields = spec_or_fields

    key_to_role: dict[str, str] = {}
    for field in fields:
        if isinstance(field, dict):
            key_to_role[field.get("key", "")] = field.get("role", "extra")
        elif isinstance(field, CredentialFieldSchema):
            key_to_role[field.key] = field.role

    return key_to_role
