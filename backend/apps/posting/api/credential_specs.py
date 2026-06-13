"""Credential Spec API — CRUD + resolve endpoints."""
from __future__ import annotations

import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.inventory.models import Game
from apps.posting.models import CredentialSpec, OfferPool
from apps.posting.services.pool.presets import (
    CREDENTIAL_PRESETS,
    get_preset,
    validate_credential_fields,
    validate_format_templates,
)
from apps.posting.services.pool.spec_resolver import (
    build_field_role_map,
    resolve_spec,
    resolve_spec_for_game_variant,
)

logger = logging.getLogger(__name__)


# ── Serialization ────────────────────────────────────────────────


def _spec_to_dict(spec: CredentialSpec) -> dict:
    role_map = build_field_role_map(spec)
    return {
        "id": spec.id,
        "name": spec.name,
        "game_id": spec.game_id,
        "game_name": spec.game.name if spec.game else "",
        "variant_id": spec.variant_id,
        "variant_label": spec.variant.label if spec.variant else None,
        "fields": spec.fields,
        "primary_keys": {
            "login": role_map.get("login", "login"),
            "password": role_map.get("password", "password"),
        },
        "format_templates": spec.format_templates,
        "is_active": spec.is_active,
        "created_at": spec.created_at.isoformat(),
        "updated_at": spec.updated_at.isoformat(),
    }


def _preset_to_dict(
    preset_key: str,
    name: str,
    fields: list[dict],
    format_templates: dict,
) -> dict:
    role_map = build_field_role_map(fields)
    return {
        "id": None,
        "name": name,
        "preset_key": preset_key,
        "fields": fields,
        "primary_keys": {
            "login": role_map.get("login", "login"),
            "password": role_map.get("password", "password"),
        },
        "format_templates": format_templates,
    }


# ── CRUD ─────────────────────────────────────────────────────────


@login_required
@require_GET
def list_specs(request):
    """List all credential specs, optionally filtered by game."""
    qs = CredentialSpec.objects.select_related("game", "variant").order_by("game__name", "name")

    game_id = request.GET.get("game_id")
    if game_id:
        qs = qs.filter(game_id=game_id)

    active_only = request.GET.get("active")
    if active_only == "true":
        qs = qs.filter(is_active=True)

    return JsonResponse({"specs": [_spec_to_dict(s) for s in qs]})


@login_required
@require_POST
def create_spec(request):
    """Create a new credential spec."""
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    game_id = body.get("game_id")
    if not game_id:
        return JsonResponse({"error": "game_id is required"}, status=400)

    try:
        game = Game.objects.get(id=game_id)
    except Game.DoesNotExist:
        return JsonResponse({"error": "Game not found"}, status=404)

    fields = body.get("fields")
    if not fields:
        return JsonResponse({"error": "fields is required"}, status=400)

    try:
        validate_credential_fields(fields)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    format_templates = body.get("format_templates", {})
    try:
        validate_format_templates(format_templates, fields)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    variant_id = body.get("variant_id")

    # Enforce unique_game_default_spec: update existing default instead of creating new
    if not variant_id:
        existing_default = CredentialSpec.objects.filter(
            game=game, variant__isnull=True
        ).first()
        if existing_default:
            existing_default.name = body.get("name", existing_default.name)
            existing_default.fields = fields
            existing_default.format_templates = format_templates
            existing_default.is_active = body.get("is_active", True)
            existing_default.full_clean()
            existing_default.save()
            return JsonResponse({"spec": _spec_to_dict(existing_default)}, status=200)

    spec = CredentialSpec(
        game=game,
        variant_id=variant_id,
        name=body.get("name", ""),
        fields=fields,
        format_templates=format_templates,
        is_active=body.get("is_active", True),
    )

    try:
        spec.full_clean()
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    spec.save()
    return JsonResponse({"spec": _spec_to_dict(spec)}, status=201)


@login_required
@require_GET
def spec_detail(request, spec_id):
    """Get a single spec by ID."""
    try:
        spec = CredentialSpec.objects.select_related("game", "variant").get(id=spec_id)
    except CredentialSpec.DoesNotExist:
        return JsonResponse({"error": "Spec not found"}, status=404)

    return JsonResponse({"spec": _spec_to_dict(spec)})


@login_required
@require_http_methods(["PUT"])
def update_spec(request, spec_id):
    """Update an existing spec."""
    try:
        spec = CredentialSpec.objects.select_related("game", "variant").get(id=spec_id)
    except CredentialSpec.DoesNotExist:
        return JsonResponse({"error": "Spec not found"}, status=404)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    if "name" in body:
        spec.name = body["name"]

    if "fields" in body:
        try:
            validate_credential_fields(body["fields"])
        except Exception as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        spec.fields = body["fields"]

    if "format_templates" in body:
        fields_for_validation = body.get("fields", spec.fields)
        try:
            validate_format_templates(body["format_templates"], fields_for_validation)
        except Exception as exc:
            return JsonResponse({"error": str(exc)}, status=400)
        spec.format_templates = body["format_templates"]

    if "is_active" in body:
        spec.is_active = bool(body["is_active"])

    try:
        spec.full_clean()
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    spec.save()
    return JsonResponse({"spec": _spec_to_dict(spec)})


@login_required
@require_http_methods(["DELETE"])
def delete_spec(request, spec_id):
    """Delete a credential spec."""
    try:
        spec = CredentialSpec.objects.get(id=spec_id)
    except CredentialSpec.DoesNotExist:
        return JsonResponse({"error": "Spec not found"}, status=404)

    # Check if any pools reference this spec
    pool_count = spec.pools.count()
    if pool_count > 0:
        return JsonResponse(
            {"error": f"Cannot delete spec — {pool_count} pool(s) reference it. Deactivate instead."},
            status=409,
        )

    spec.delete()
    return JsonResponse({"ok": True})


# ── Resolve Endpoints ────────────────────────────────────────────


@login_required
@require_GET
def resolve_for_pool(request, pool_id):
    """Resolve the effective spec for a pool.

    GET /posting/api/credential-specs/for-pool/<pool_id>/
    """
    try:
        pool = (
            OfferPool.objects
            .select_related("game", "listing", "credential_spec")
            .get(id=pool_id)
        )
    except OfferPool.DoesNotExist:
        return JsonResponse({"error": "Pool not found"}, status=404)

    spec = resolve_spec(pool)
    if spec:
        return JsonResponse({
            "spec": _spec_to_dict(spec),
            "source": _determine_source(pool, spec),
        })

    # No DB spec — return code-level preset
    game_slug = pool.game.slug if pool.game else ""
    variant_value = getattr(pool.listing, "variant", None) if pool.listing else None
    preset = get_preset(game_slug, _variant_slug_from_value(pool.game, variant_value))
    if preset:
        return JsonResponse({
            "spec": _preset_to_dict(f"{game_slug}", preset[0], preset[1], preset[2]),
            "source": "preset",
        })

    return JsonResponse({"spec": None, "source": "none"})


@login_required
@require_GET
def resolve_by_query(request):
    """Resolve spec by game_id and optional variant string.

    GET /posting/api/credential-specs/resolve/?game_id=<id>&variant=<slug>
    """
    game_id = request.GET.get("game_id")
    if not game_id:
        return JsonResponse({"error": "game_id is required"}, status=400)

    try:
        game = Game.objects.get(id=game_id)
    except Game.DoesNotExist:
        return JsonResponse({"error": "Game not found"}, status=404)

    variant_value = request.GET.get("variant", "").strip()
    spec = resolve_spec_for_game_variant(game, variant_value or None)

    if spec:
        source = "variant" if spec.variant_id else "game"
        return JsonResponse({
            "spec": _spec_to_dict(spec),
            "source": source,
        })

    # Code-level preset fallback
    variant_slug = _variant_slug_from_value(game, variant_value) if variant_value else None
    preset = get_preset(game.slug, variant_slug)
    if preset:
        return JsonResponse({
            "spec": _preset_to_dict(
                f"{game.slug}:{variant_slug}" if variant_slug else game.slug,
                preset[0],
                preset[1],
                preset[2],
            ),
            "source": "preset",
        })

    return JsonResponse({"spec": None, "source": "none"})


@login_required
@require_GET
def list_presets(request):
    """List all code-level credential presets.

    GET /posting/api/credential-specs/presets/
    """
    presets = []
    for key, (name, fields, templates) in CREDENTIAL_PRESETS.items():
        presets.append(_preset_to_dict(key, name, fields, templates))
    return JsonResponse({"presets": presets})


# ── Helpers ──────────────────────────────────────────────────────


def _determine_source(pool: OfferPool, spec: CredentialSpec) -> str:
    if pool.credential_spec_id == spec.id:
        return "explicit"
    if spec.variant_id:
        return "variant"
    return "game"


def _variant_slug_from_value(game, variant_value: str | None) -> str | None:
    """Try to resolve variant value to a slug for preset lookup."""
    if not variant_value or not game:
        return None
    from apps.posting.services.pool.spec_resolver import resolve_game_variant
    variant = resolve_game_variant(game, variant_value)
    return variant.slug if variant else None
