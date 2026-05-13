"""Content template CRUD + preview API."""

from __future__ import annotations

import json
from typing import Any

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.accounts.decorators import role_required
from apps.inventory.models import Game
from apps.posting.models import ContentTemplate
from payload_pipeline.content_templates import (
    SimpleTemplateRenderer,
    TemplateRenderError,
    TemplateValidationError,
    get_field_registry,
    get_resolved_model_name,
    get_sample_context,
    validate_template,
)
from payload_pipeline.content_templates.field_registry import get_available_fields


@role_required('admin', 'user')
@require_GET
def list_content_templates(request):
    """Return templates for a game, optionally filtered by marketplace/type."""
    game_id = request.GET.get('game_id')
    if not game_id:
        return JsonResponse({'error': 'game_id is required'}, status=400)

    qs = ContentTemplate.objects.filter(game_id=game_id)

    marketplace = request.GET.get('marketplace')
    if marketplace:
        qs = qs.filter(marketplace=marketplace)

    template_type = request.GET.get('template_type')
    if template_type:
        qs = qs.filter(template_type=template_type)

    return JsonResponse({
        'templates': [_serialize(t) for t in qs],
    })


@role_required('admin', 'user')
@require_GET
def content_template_metadata(request):
    """Return available fields and model info for the template editor."""
    game_id = request.GET.get('game_id')
    category = request.GET.get('category') or 'account'
    game_slug = _game_slug(game_id)

    return JsonResponse({
        'fields': get_field_registry(game_slug, category),
        'model': get_resolved_model_name(game_slug, category),
    })


@role_required('admin', 'user')
@require_POST
def create_content_template(request):
    """Create a new content template."""
    body = _parse_json(request)
    if isinstance(body, JsonResponse):
        return body

    game_id = body.get('game_id')
    marketplace = body.get('marketplace')
    template_type = body.get('template_type')
    name = body.get('name', '').strip()
    template_body = body.get('body', '')

    if not all([game_id, marketplace, template_type, name, template_body]):
        return JsonResponse(
            {'error': 'game_id, marketplace, template_type, name, and body are required'},
            status=400,
        )

    try:
        game = Game.objects.get(id=game_id)
    except Game.DoesNotExist:
        return JsonResponse({'error': 'Game not found'}, status=404)

    # Validate template body
    game_slug = game.slug if game else ''
    available = get_available_fields(game_slug) if game_slug else None
    warnings = _validate_body(template_body, template_type, available)
    if isinstance(warnings, JsonResponse):
        return warnings

    template = ContentTemplate(
        game=game,
        marketplace=marketplace,
        template_type=template_type,
        name=name,
        body=template_body,
    )
    try:
        template.full_clean()
        template.save()
    except ValidationError as exc:
        return JsonResponse({'error': _validation_message(exc)}, status=400)

    return JsonResponse({
        'ok': True,
        'template': _serialize(template),
        'warnings': warnings,
    })


@role_required('admin', 'user')
@require_http_methods(['POST', 'DELETE'])
def content_template_detail(request, template_id: int):
    """Update or delete a content template."""
    try:
        template = ContentTemplate.objects.get(id=template_id)
    except ContentTemplate.DoesNotExist:
        return JsonResponse({'error': 'Template not found'}, status=404)

    if request.method == 'DELETE':
        template.delete()
        return JsonResponse({'ok': True})

    body = _parse_json(request)
    if isinstance(body, JsonResponse):
        return body

    name = body.get('name', '').strip()
    template_body = body.get('body', '')

    if not name or not template_body:
        return JsonResponse({'error': 'name and body are required'}, status=400)

    # Validate
    game_slug = template.game.slug if template.game else ''
    available = get_available_fields(game_slug) if game_slug else None
    warnings = _validate_body(template_body, template.template_type, available)
    if isinstance(warnings, JsonResponse):
        return warnings

    template.name = name
    template.body = template_body
    try:
        template.full_clean()
        template.save()
    except ValidationError as exc:
        return JsonResponse({'error': _validation_message(exc)}, status=400)

    return JsonResponse({
        'ok': True,
        'template': _serialize(template),
        'warnings': warnings,
    })


@role_required('admin', 'user')
@require_POST
def preview_content_template(request):
    """Render a template body with sample context and return the result."""
    body = _parse_json(request)
    if isinstance(body, JsonResponse):
        return body

    template_body = body.get('body', '')
    template_type = body.get('template_type', '')
    game_id = body.get('game_id')
    category = body.get('category') or 'account'

    if not template_body:
        return JsonResponse({'error': 'body is required'}, status=400)

    game_slug = _game_slug(game_id)
    available = get_available_fields(game_slug) if game_slug else None

    # Validate
    warnings = _validate_body(template_body, template_type, available)
    if isinstance(warnings, JsonResponse):
        return warnings

    # Render with sample context
    context = get_sample_context(game_slug, category)
    try:
        renderer = SimpleTemplateRenderer()
        rendered = renderer.render(template_body, context)
    except TemplateRenderError as exc:
        return JsonResponse({'error': str(exc)}, status=400)

    return JsonResponse({
        'ok': True,
        'rendered': rendered,
        'warnings': warnings,
        'context': context,
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize(template: ContentTemplate) -> dict[str, Any]:
    return {
        'id': template.id,
        'game_id': template.game_id,
        'marketplace': template.marketplace,
        'template_type': template.template_type,
        'name': template.name,
        'body': template.body,
        'created_at': template.created_at.isoformat() if template.created_at else None,
        'updated_at': template.updated_at.isoformat() if template.updated_at else None,
    }


def _parse_json(request) -> dict | JsonResponse:
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


def _validate_body(
    template_body: str,
    template_type: str,
    available_fields: set[str] | None,
) -> list[str] | JsonResponse:
    """Validate and return warnings, or a JsonResponse on error."""
    try:
        return validate_template(
            template_body,
            template_type=template_type,
            available_fields=available_fields,
        )
    except TemplateValidationError as exc:
        return JsonResponse({'error': str(exc)}, status=400)


def _validation_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        if hasattr(exc, 'message_dict'):
            parts = []
            for field, messages in exc.message_dict.items():
                parts.extend(str(m) for m in messages)
            return '; '.join(parts)
        if hasattr(exc, 'messages'):
            return '; '.join(str(msg) for msg in exc.messages)
    return str(exc)


def _game_slug(game_id: Any) -> str:
    if not game_id:
        return ''
    game = Game.objects.filter(id=game_id).first()
    return game.slug if game else ''
