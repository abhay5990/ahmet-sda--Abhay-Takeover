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

_MAX_UPLOAD_BYTES = 8 * 1024 * 1024
_ALLOWED_IMAGE_FORMATS = {
    'PNG': ('image/png', '.png'),
    'JPEG': ('image/jpeg', '.jpg'),
}


def _serialize_preset(preset: PostingImagePreset) -> dict:
    return {
        'id': preset.id,
        'name': preset.name,
        'url': preset.image.url if preset.image else '',
        'width': preset.width,
        'height': preset.height,
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
        return b'', '', '', 0, 0, 'image must be 8 MB or smaller'

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
        return b'', '', '', 0, 0, 'image must be a valid PNG or JPEG file'

    if image_format not in _ALLOWED_IMAGE_FORMATS:
        return b'', '', '', 0, 0, 'only PNG and JPEG images are supported'

    mime_type, ext = _ALLOWED_IMAGE_FORMATS[image_format]
    return data, digest.hexdigest(), mime_type, width, height, None


@login_required
@require_GET
def list_image_presets(request):
    game = _get_game(request.GET.get('game_id'))
    if game is None:
        return JsonResponse({'error': 'game_id is required'}, status=400)

    presets = PostingImagePreset.objects.filter(
        user=request.user,
        game=game,
        is_active=True,
    )
    return JsonResponse({'presets': [_serialize_preset(preset) for preset in presets]})


@login_required
@require_POST
def upload_image_preset(request):
    game = _get_game(request.POST.get('game_id'))
    if game is None:
        return JsonResponse({'error': 'game_id is required'}, status=400)

    uploaded = request.FILES.get('image')
    data, digest, mime_type, width, height, error = _read_and_validate_image(uploaded)
    if error:
        return JsonResponse({'error': error}, status=400)

    name = (request.POST.get('name') or '').strip()
    if not name and uploaded:
        name = Path(uploaded.name).stem
    name = name[:120]

    existing = PostingImagePreset.objects.filter(
        user=request.user,
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

    _, ext = _ALLOWED_IMAGE_FORMATS['PNG' if mime_type == 'image/png' else 'JPEG']
    preset = PostingImagePreset(
        user=request.user,
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
        user=request.user,
        is_active=True,
    ).first()
    if not preset:
        return JsonResponse({'error': 'Image preset not found'}, status=404)

    preset.is_active = False
    preset.save(update_fields=['is_active', 'updated_at'])
    return JsonResponse({'ok': True})
