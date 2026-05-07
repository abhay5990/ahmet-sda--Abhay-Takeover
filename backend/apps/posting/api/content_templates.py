"""Content template override API."""

from __future__ import annotations

import json
import importlib
import inspect
from dataclasses import fields, is_dataclass
from functools import lru_cache
from typing import Any
from typing import get_args, get_origin, get_type_hints

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.inventory.models import Game
from apps.posting.models import ContentTemplateOverride
from payload_pipeline import build_default_registry
from payload_pipeline.content_templates import (
    TemplateDescriptionGenerator,
    TemplateRenderError,
    TemplateTitleGenerator,
)
from payload_pipeline.core.contracts import ResolvedAccountBase
from payload_pipeline.core.enums import ListingCategory


@login_required
@require_GET
def list_content_templates(request):
    """Return overrides for a game/category/kind."""
    game_id = request.GET.get('game_id')
    kind = request.GET.get('kind', 'stock')
    category = request.GET.get('category', 'account')
    if not game_id:
        return JsonResponse({'error': 'game_id is required'}, status=400)

    rows = (
        ContentTemplateOverride.objects
        .filter(game_id=game_id, category=category, kind=kind)
        .order_by('marketplace')
    )
    return JsonResponse({
        'templates': [_serialize_template(row) for row in rows],
    })


@login_required
@require_GET
def content_template_metadata(request):
    """Return supported fields and template syntax for the selected game."""
    game_id = request.GET.get('game_id')
    category = request.GET.get('category') or 'account'
    game_slug = ''
    if game_id:
        game = Game.objects.filter(id=game_id).first()
        game_slug = game.slug if game else ''
    model_type = _resolved_model_type(game_slug, category)

    return JsonResponse({
        'fields': _field_metadata(game_slug, category),
        'model': model_type.__name__ if model_type else '',
        'syntax': _syntax_metadata(),
    })


@login_required
@require_http_methods(['POST', 'DELETE'])
def content_template_detail(request, template_id: int | None = None):
    """Create/update or delete one content template override."""
    if request.method == 'DELETE':
        if template_id is None:
            return JsonResponse({'error': 'template_id is required'}, status=400)
        deleted, _ = ContentTemplateOverride.objects.filter(id=template_id).delete()
        return JsonResponse({'ok': bool(deleted)})

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    game_id = body.get('game_id')
    marketplace = body.get('marketplace')
    if not game_id or not marketplace:
        return JsonResponse({'error': 'game_id and marketplace are required'}, status=400)

    try:
        game = Game.objects.get(id=game_id)
    except Game.DoesNotExist:
        return JsonResponse({'error': 'Game not found'}, status=404)

    defaults = {
        'enabled': bool(body.get('enabled', True)),
        'title_template': _template_or_none(body.get('title_template')),
        'description_template': _template_or_none(body.get('description_template')),
        'notes': str(body.get('notes') or ''),
    }
    lookup = {
        'game': game,
        'category': body.get('category') or 'account',
        'kind': body.get('kind') or 'stock',
        'marketplace': marketplace,
    }
    template, created = ContentTemplateOverride.objects.get_or_create(
        **lookup,
        defaults=defaults,
    )
    if not created:
        for field, value in defaults.items():
            setattr(template, field, value)

    try:
        template.full_clean()
    except ValidationError as exc:
        if created:
            template.delete()
        return JsonResponse({'error': _validation_message(exc)}, status=400)

    template.save()
    return JsonResponse({'ok': True, 'template': _serialize_template(template)})


@login_required
@require_POST
def preview_content_template(request):
    """Validate and render submitted template specs with sample context."""
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    title_template = _template_or_none(body.get('title_template'))
    description_template = _template_or_none(body.get('description_template'))

    draft = ContentTemplateOverride(
        game_id=body.get('game_id') or None,
        category=body.get('category') or 'account',
        kind=body.get('kind') or 'stock',
        marketplace=body.get('marketplace') or 'default',
        enabled=True,
        title_template=title_template,
        description_template=description_template,
    )
    try:
        draft.clean()
        game_slug = _game_slug(body.get('game_id'))
        context = _sample_context(game_slug, body.get('category') or 'account')
        title = (
            TemplateTitleGenerator().generate(title_template, context)
            if title_template
            else ''
        )
        description = (
            TemplateDescriptionGenerator().generate(description_template, context)
            if description_template
            else ''
        )
    except (ValidationError, TemplateRenderError) as exc:
        return JsonResponse({'error': _validation_message(exc)}, status=400)

    return JsonResponse({
        'ok': True,
        'title': title,
        'description': description,
    })


def _serialize_template(template: ContentTemplateOverride) -> dict[str, Any]:
    return {
        'id': template.id,
        'game_id': template.game_id,
        'category': template.category,
        'kind': template.kind,
        'marketplace': template.marketplace,
        'enabled': template.enabled,
        'title_template': template.title_template,
        'description_template': template.description_template,
        'notes': template.notes,
        'updated_at': template.updated_at.isoformat() if template.updated_at else None,
    }


def _template_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) and value else None


def _validation_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        if hasattr(exc, 'messages'):
            return '; '.join(str(msg) for msg in exc.messages)
        return str(exc)
    return str(exc)


def _game_slug(game_id: Any) -> str:
    if not game_id:
        return ''
    game = Game.objects.filter(id=game_id).first()
    return game.slug if game else ''


def _sample_context(game_slug: str, category: str = 'account') -> dict[str, Any]:
    model_type = _resolved_model_type(game_slug, category)
    context: dict[str, Any] = {}
    if model_type:
        type_hints = _safe_type_hints(model_type)
        for field in fields(model_type):
            if field.name == 'credentials':
                continue
            context[field.name] = _sample_for_field(field.name, type_hints.get(field.name, field.type))
    else:
        type_hints = _safe_type_hints(ResolvedAccountBase)
        for field in fields(ResolvedAccountBase):
            if field.name == 'credentials':
                continue
            context[field.name] = _sample_for_field(field.name, type_hints.get(field.name, field.type))

    context.update(_computed_context(game_slug))
    return context


def _field_metadata(game_slug: str, category: str = 'account') -> list[dict[str, str]]:
    sample = _sample_context(game_slug, category)
    model_type = _resolved_model_type(game_slug, category)
    resolved_fields = _resolved_field_names(model_type)
    computed_fields = set(_computed_context(game_slug))
    descriptions = {
        'item_id': 'Source item ID.',
        'price': 'Listing price from the resolved account.',
        'kind': 'stock or dropshipping.',
        'username': 'Account username.',
        'roblox_id': 'Roblox numeric user ID.',
        'profile_url': 'Roblox profile URL.',
        'robux': 'Current Robux balance.',
        'incoming_robux_total': 'Total Robux spent/incoming value from source.',
        'inventory_price': 'Classic inventory value before integer formatting.',
        'inventory_price_int': 'Classic inventory value as an integer.',
        'ugc_limited_price': 'UGC limited value before integer formatting.',
        'ugc_limited_price_int': 'UGC limited value as an integer.',
        'limited_price': 'Limited value from the resolved account.',
        'game_pass_total_robux': 'Total gamepass Robux value.',
        'offsale_count': 'Offsale item count.',
        'friends': 'Friend count.',
        'followers': 'Follower count.',
        'age_verified': 'Raw age verification boolean.',
        'age_verified_label': 'Yes/No label for age verification.',
        'email_verified': 'Email verification boolean.',
        'verified': 'General verification boolean.',
        'register_date': 'Registration date formatted as YYYY-MM-DD.',
        'register_year': 'Registration year.',
        'country': 'Resolved account country.',
        'has_subscription': 'Subscription status boolean.',
        'voice_enabled': 'Voice feature status boolean.',
        'xbox_connected': 'Xbox connection status boolean.',
        'psn_connected': 'PSN connection status boolean.',
        'has_email_access': 'Email access status boolean.',
        'letter_tag': '3 Letter, / 4 Letter, prefix for title templates.',
        'letter_label': '3 Letter / 4 Letter label without punctuation.',
        'is_stock': 'True for stock listings.',
        'album_url': 'Hosted media album URL when available.',
    }

    metadata: list[dict[str, str]] = []
    for key, value in sample.items():
        source = 'resolved' if key in resolved_fields else 'runtime'
        if key in computed_fields:
            source = 'computed'
        metadata.append({
            'name': key,
            'placeholder': '{' + key + '}',
            'sample': _sample_value(value),
            'source': source,
            'description': descriptions.get(key, _humanize_field(key)),
        })
    return metadata


@lru_cache(maxsize=64)
def _resolved_model_type(game_slug: str, category: str = 'account') -> type[ResolvedAccountBase] | None:
    if not game_slug:
        return None

    try:
        definition = build_default_registry().get_game(
            game_slug,
            _listing_category(category),
        )
    except Exception:
        return None

    return (
        _resolver_return_model(definition.resolver)
        or _model_from_resolver_module(definition.resolver.__class__.__module__)
    )


def _listing_category(value: str) -> ListingCategory:
    try:
        return ListingCategory(value or 'account')
    except ValueError:
        return ListingCategory.ACCOUNT


def _resolver_return_model(resolver: Any) -> type[ResolvedAccountBase] | None:
    try:
        return_type = get_type_hints(resolver.resolve).get('return')
    except Exception:
        return None
    if _is_resolved_model(return_type):
        return return_type
    return None


def _model_from_resolver_module(module_name: str) -> type[ResolvedAccountBase] | None:
    package_name = module_name.rsplit('.', 1)[0]
    try:
        module = importlib.import_module(f'{package_name}.models')
    except Exception:
        return None

    for _, value in inspect.getmembers(module, inspect.isclass):
        if _is_resolved_model(value):
            return value
    return None


def _is_resolved_model(value: Any) -> bool:
    return (
        inspect.isclass(value)
        and value is not ResolvedAccountBase
        and issubclass(value, ResolvedAccountBase)
        and is_dataclass(value)
    )


def _resolved_field_names(model_type: type[ResolvedAccountBase] | None) -> set[str]:
    if model_type is None:
        return set()
    return {field.name for field in fields(model_type) if field.name != 'credentials'}


def _computed_context(game_slug: str) -> dict[str, Any]:
    context: dict[str, Any] = {
        'album_url': 'https://imgur.com/a/sample',
        'is_stock': True,
    }
    if game_slug == 'roblox':
        context.update({
            'profile_url': 'https://www.roblox.com/users/123456789/profile',
            'inventory_price_int': 8500,
            'ugc_limited_price_int': 3200,
            'age_verified_label': 'Yes',
            'register_date': '2000-01-01',
            'register_year': '2000',
            'letter_tag': '4 Letter, ',
            'letter_label': '4 Letter',
        })
    return context


_SAMPLE_BY_NAME: dict[str, Any] = {
    'item_id': 'sample-item-123',
    'category_id': 1,
    'price': 10.0,
    'kind': 'stock',
    'username': 'sampleuser',
    'roblox_id': 123456789,
    'robux': 5000,
    'incoming_robux_total': 1200,
    'inventory_price': 8500.50,
    'ugc_limited_price': 3200.0,
    'limited_price': 0.0,
    'game_pass_total_robux': 777,
    'offsale_count': 42,
    'friends': 128,
    'followers': 2400,
    'age_verified': True,
    'email_verified': True,
    'verified': True,
    'country': 'US',
    'has_subscription': False,
    'voice_enabled': True,
    'xbox_connected': False,
    'psn_connected': False,
    'has_email_access': True,
    'region': 'EU',
    'level': 44,
    'rank': 'Gold',
    'current_rank': 'Gold',
    'previous_rank': 'Platinum',
    'last_rank': 'Gold',
    'skin_count': 81,
    'agent_count': 22,
    'knife_count': 8,
    'inventory_value': 12500,
    'skin_names': ['Prime Vandal', 'Reaver Knife', 'Ion Sheriff'],
    'agent_names': ['Jett', 'Reyna', 'Sage'],
    'cosmetic_titles': ['Renegade Raider', 'Black Knight', 'Scenario'],
    'operators': ['Ash', 'Jager', 'Mira'],
}


def _sample_for_field(name: str, field_type: Any) -> Any:
    if name in _SAMPLE_BY_NAME:
        return _SAMPLE_BY_NAME[name]
    origin = get_origin(field_type)
    args = set(get_args(field_type))
    if origin in {list, tuple, set}:
        return ['Item A', 'Item B', 'Item C']
    if origin is dict:
        return {'sample': 'value'}
    if field_type is bool or bool in args or name.startswith(('has_', 'is_', 'can_')):
        return True
    if field_type is int or name.endswith(('_count', '_level', '_value', '_total')):
        return 1
    if field_type is float:
        return 1.0
    return 'sample'


def _safe_type_hints(model_type: type[Any]) -> dict[str, Any]:
    try:
        return get_type_hints(model_type)
    except Exception:
        return {}


def _sample_value(value: Any) -> str:
    if isinstance(value, list):
        return ', '.join(str(item) for item in value[:3])
    if isinstance(value, dict):
        return json.dumps(value)
    return str(value)


def _humanize_field(value: str) -> str:
    return value.replace('_', ' ').capitalize() + '.'


def _syntax_metadata() -> dict[str, Any]:
    return {
        'title_part_sources': [
            {'key': 'text', 'label': 'Static text', 'example': '{"text": "Full Access"}'},
            {'key': 'field', 'label': 'Render one field', 'example': '{"field": "letter_label", "when": {"truthy": "letter_label"}}'},
            {'key': 'template', 'label': 'Format text with fields', 'example': '{"template": "{incoming_robux_total} R$ Spent"}'},
            {'key': 'list', 'label': 'Render list items', 'example': '{"list": "priority_items", "limit": 2}'},
        ],
        'description_blocks': [
            {'type': 'line', 'label': 'Single line', 'example': '{"type": "line", "template": "Username: {username}"}'},
            {'type': 'blank', 'label': 'Blank line', 'example': '{"type": "blank"}'},
            {'type': 'lines', 'label': 'Multiple lines', 'example': '{"type": "lines", "items": ["Line A", {"template": "Robux: {robux}"}]}'},
            {'type': 'section', 'label': 'List section', 'example': '{"type": "section", "title": "Items:", "items": "items", "limit": 3}'},
        ],
        'conditions': [
            {'op': 'truthy', 'example': '{"truthy": "letter_label"}'},
            {'op': 'falsy', 'example': '{"falsy": "album_url"}'},
            {'op': 'gt/gte/lt/lte', 'example': '{"gt": ["offsale_count", 0]}'},
            {'op': 'eq/neq', 'example': '{"neq": ["rank", "Unranked"]}'},
            {'op': 'contains', 'example': '{"contains": ["items", "Item A"]}'},
            {'op': 'and/or/not', 'example': '{"and": [{"truthy": "is_stock"}, {"gt": ["robux", 0]}]}'},
        ],
    }
