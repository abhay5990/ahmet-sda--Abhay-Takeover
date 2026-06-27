"""API endpoint for game-specific manual entry field specs."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from apps.inventory.models import Game
from payload_pipeline import build_default_registry
from payload_pipeline.core.manual_fields import manual_field_registry

# Ensure game modules are imported so manual_field_registry is populated.
_registry_loaded = False


def _ensure_registry_loaded() -> None:
    global _registry_loaded
    if not _registry_loaded:
        build_default_registry()
        _registry_loaded = True


def _game_slug(game: Game) -> str:
    return game.slug or game.name.lower().replace(" ", "-")


def validate_manual_fields_for_game(
    game: Game,
    values: dict | None,
) -> tuple[dict, JsonResponse | None]:
    """Validate submitted manual_fields for a game."""

    _ensure_registry_loaded()
    slug = _game_slug(game)
    normalized, errors = manual_field_registry.validate_values(slug, values)
    if errors:
        return {}, JsonResponse(
            {
                "error": "Invalid manual_fields",
                "details": errors,
            },
            status=400,
        )
    return normalized, None


@login_required
@require_GET
def manual_field_specs(request):
    """Return manual entry field specifications for a game.

    GET /posting/api/manual-fields/?game_id=<int>

    Response: { "game": "<slug>", "fields": [...] }
    """
    _ensure_registry_loaded()

    game_id = request.GET.get("game_id")
    if not game_id:
        return JsonResponse({"error": "game_id is required"}, status=400)

    try:
        game = Game.objects.get(pk=int(game_id))
    except (Game.DoesNotExist, ValueError, TypeError):
        return JsonResponse({"error": "Game not found"}, status=404)

    slug = _game_slug(game)

    fields = manual_field_registry.serialize(slug)

    return JsonResponse({"game": slug, "fields": fields})
