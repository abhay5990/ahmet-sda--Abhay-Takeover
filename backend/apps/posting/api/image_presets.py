"""Reusable image preset endpoints for posting flows."""

from __future__ import annotations

from io import BytesIO
import hashlib
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from PIL import Image, UnidentifiedImageError

from apps.inventory.models import Game
from apps.posting.models import PostingImagePreset
from payload_pipeline import build_default_registry

_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MB
_MAX_PRESETS_PER_GAME = 50
_ALLOWED_IMAGE_FORMATS = {
    'PNG': ('image/png', '.png'),
    'JPEG': ('image/jpeg', '.jpg'),
    'WEBP': ('image/webp', '.webp'),
}


def _serialize_preset(preset: PostingImagePreset) -> dict:
    return {
        'id': preset.id,
        'name': preset.name,
        'url': preset.image.url if preset.image else '',
        'width': preset.width,
        'height': preset.height,
        'size_bytes': preset.size_bytes,
        'sha256': preset.sha256,
        'created_at': preset.created_at.isoformat(),
        'last_used_at': preset.last_used_at.isoformat() if preset.last_used_at else None,
    }


def _get_game(game_id) -> Game | None:
    try:
        return Game.objects.get(id=game_id, is_active=True)
    except (Game.DoesNotExist, ValueError, TypeError):
        return None


def _read_and_validate_image(uploaded) -> tuple[bytes, str, str, int, int, str | None]:
    if not uploaded:
        return b'', '', '', 0, 0, 'image is required'
    if uploaded.size > _MAX_UPLOAD_BYTES:
        return b'', '', '', 0, 0, f'image must be {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB or smaller'

    chunks: list[bytes] = []
    digest = hashlib.sha256()
    for chunk in uploaded.chunks():
        digest.update(chunk)
        chunks.append(chunk)
    data = b''.join(chunks)

    try:
        with Image.open(BytesIO(data)) as img:
            image_format = img.format
            width, height = img.size
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError):
        return b'', '', '', 0, 0, 'image must be a valid PNG, JPEG, or WebP file'

    if image_format not in _ALLOWED_IMAGE_FORMATS:
        return b'', '', '', 0, 0, 'only PNG, JPEG, and WebP images are supported'

    mime_type, ext = _ALLOWED_IMAGE_FORMATS[image_format]
    return data, digest.hexdigest(), mime_type, width, height, None


@login_required
@require_GET
def list_image_presets(request):
    game = _get_game(request.GET.get('game_id'))
    if game is None:
        return JsonResponse({'error': 'game_id is required'}, status=400)

    presets = PostingImagePreset.objects.filter(
        game=game,
        is_active=True,
    )
    return JsonResponse({
        'presets': [_serialize_preset(preset) for preset in presets],
        'limit': _MAX_PRESETS_PER_GAME,
    })


@login_required
@require_POST
def upload_image_preset(request):
    game = _get_game(request.POST.get('game_id'))
    if game is None:
        return JsonResponse({'error': 'game_id is required'}, status=400)

    # Check per-game limit
    active_count = PostingImagePreset.objects.filter(
        game=game,
        is_active=True,
    ).count()
    if active_count >= _MAX_PRESETS_PER_GAME:
        return JsonResponse({
            'error': f'Maximum {_MAX_PRESETS_PER_GAME} images per game reached. '
                     'Delete some images before uploading new ones.',
        }, status=400)

    uploaded = request.FILES.get('image')
    data, digest, mime_type, width, height, error = _read_and_validate_image(uploaded)
    if error:
        return JsonResponse({'error': error}, status=400)

    name = (request.POST.get('name') or '').strip()
    if not name and uploaded:
        name = Path(uploaded.name).stem
    name = name[:120]

    existing = PostingImagePreset.objects.filter(
        game=game,
        sha256=digest,
    ).first()
    if existing:
        update_fields = ['last_used_at', 'updated_at']
        existing.last_used_at = timezone.now()
        if not existing.is_active:
            existing.is_active = True
            update_fields.append('is_active')
        if name and not existing.name:
            existing.name = name
            update_fields.append('name')
        existing.save(update_fields=update_fields)
        return JsonResponse({
            'preset': _serialize_preset(existing),
            'deduplicated': True,
        })

    fmt_key = next((k for k, v in _ALLOWED_IMAGE_FORMATS.items() if v[0] == mime_type), 'JPEG')
    _, ext = _ALLOWED_IMAGE_FORMATS[fmt_key]
    preset = PostingImagePreset(
        uploaded_by=request.user,
        game=game,
        name=name,
        sha256=digest,
        mime_type=mime_type,
        size_bytes=len(data),
        width=width,
        height=height,
        last_used_at=timezone.now(),
    )
    preset.image.save(f'{digest[:24]}{ext}', ContentFile(data), save=False)
    preset.save()

    return JsonResponse({
        'preset': _serialize_preset(preset),
        'deduplicated': False,
    }, status=201)


@login_required
@require_POST
def delete_image_preset(request, preset_id: int):
    preset = PostingImagePreset.objects.filter(
        id=preset_id,
        is_active=True,
    ).first()
    if not preset:
        return JsonResponse({'error': 'Image preset not found'}, status=404)

    preset.is_active = False
    preset.save(update_fields=['is_active', 'updated_at'])
    return JsonResponse({'ok': True})


# ── Lazy singleton for the pipeline registry (avoid re-creating per request)
_registry = None


def _get_registry():
    global _registry
    if _registry is None:
        _registry = build_default_registry()
    return _registry


@login_required
@require_GET
def media_capabilities(request):
    """Return media capabilities for a game (auto-gen, override support)."""
    game = _get_game(request.GET.get('game_id'))
    if game is None:
        return JsonResponse({'error': 'game_id is required'}, status=400)

    registry = _get_registry()
    caps = registry.get_media_capabilities(game.slug)
    return JsonResponse({
        'auto_generate_manual': caps.auto_generate_manual,
        'supports_override': caps.supports_override,
    })
