"""CosmeticList CRUD API — manage dynamic cosmetic matching lists."""

from __future__ import annotations

import json
from typing import Any

from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.decorators import role_required
from apps.inventory.models import Game
from apps.posting.models import CosmeticList


@role_required('admin', 'user')
@require_GET
def list_cosmetic_lists(request):
    """Return all cosmetic lists, optionally filtered by game_id."""
    game_id = request.GET.get('game_id')
    qs = CosmeticList.objects.select_related('game')
    if game_id:
        qs = qs.filter(game_id=game_id)
    return JsonResponse({
        'lists': [_serialize(cl) for cl in qs],
    })


@role_required('admin', 'user')
@require_POST
def create_cosmetic_list(request):
    """Create a new cosmetic list."""
    body = _parse_json(request)
    if isinstance(body, JsonResponse):
        return body

    game_id = body.get('game_id')
    name = body.get('name', '').strip()
    slug = body.get('slug', '').strip().lower()
    items = body.get('items', [])
    match_field = body.get('match_field', 'cosmetic_titles')
    priority = body.get('priority', 0)

    if not all([game_id, name, slug]):
        return JsonResponse(
            {'error': 'game_id, name, and slug are required'}, status=400,
        )

    try:
        game = Game.objects.get(id=game_id)
    except Game.DoesNotExist:
        return JsonResponse({'error': 'Game not found'}, status=404)

    if CosmeticList.objects.filter(game=game, slug=slug).exists():
        return JsonResponse(
            {'error': f'A list with slug "{slug}" already exists for this game'},
            status=400,
        )

    # Normalize items: split text lines into a list if string provided
    items = _normalize_items(items)

    cl = CosmeticList.objects.create(
        game=game,
        name=name,
        slug=slug,
        items=items,
        match_field=match_field,
        priority=priority,
    )
    return JsonResponse({'ok': True, 'list': _serialize(cl)})


@role_required('admin', 'user')
@require_http_methods(['POST', 'DELETE'])
def cosmetic_list_detail(request, list_id: int):
    """Update or delete a cosmetic list."""
    try:
        cl = CosmeticList.objects.get(id=list_id)
    except CosmeticList.DoesNotExist:
        return JsonResponse({'error': 'List not found'}, status=404)

    if request.method == 'DELETE':
        cl.delete()
        return JsonResponse({'ok': True})

    body = _parse_json(request)
    if isinstance(body, JsonResponse):
        return body

    if 'name' in body:
        cl.name = body['name'].strip()
    if 'items' in body:
        cl.items = _normalize_items(body['items'])
    if 'match_field' in body:
        cl.match_field = body['match_field']
    if 'priority' in body:
        cl.priority = body['priority']
    if 'is_active' in body:
        cl.is_active = body['is_active']

    cl.save()
    return JsonResponse({'ok': True, 'list': _serialize(cl)})


@role_required('admin', 'user')
@require_POST
def reorder_cosmetic_lists(request):
    """Bulk update priorities. Expects {"order": [id1, id2, id3, ...]}."""
    body = _parse_json(request)
    if isinstance(body, JsonResponse):
        return body

    order = body.get('order', [])
    if not order:
        return JsonResponse({'error': 'order is required'}, status=400)

    for idx, list_id in enumerate(order):
        CosmeticList.objects.filter(id=list_id).update(priority=idx)

    return JsonResponse({'ok': True})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize(cl: CosmeticList) -> dict[str, Any]:
    return {
        'id': cl.id,
        'game_id': cl.game_id,
        'game_name': cl.game.name if cl.game else '',
        'name': cl.name,
        'slug': cl.slug,
        'items': cl.items,
        'match_field': cl.match_field,
        'priority': cl.priority,
        'is_active': cl.is_active,
        'created_at': cl.created_at.isoformat() if cl.created_at else None,
        'updated_at': cl.updated_at.isoformat() if cl.updated_at else None,
    }


def _parse_json(request) -> dict | JsonResponse:
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


def _normalize_items(items: Any) -> list[str]:
    """Accept items as list or newline-separated string."""
    if isinstance(items, str):
        return [line.strip() for line in items.splitlines() if line.strip()]
    if isinstance(items, list):
        return [str(item).strip() for item in items if str(item).strip()]
    return []
