"""Shared image override helpers for posting job creation."""

from __future__ import annotations

from pathlib import Path

from django.http import JsonResponse
from django.utils import timezone

from apps.inventory.models import Game
from apps.posting.models import PostingImagePreset


def resolve_image_override_settings(
    body: dict,
    game: Game,
) -> tuple[dict, JsonResponse | None]:
    """Validate a selected image preset and return job settings metadata."""

    preset_id = body.get('selected_image_preset_id')
    if preset_id in (None, '', 'auto'):
        return {}, None

    try:
        preset_id = int(preset_id)
    except (TypeError, ValueError):
        return {}, JsonResponse(
            {'error': 'selected_image_preset_id must be a number'},
            status=400,
        )

    preset = PostingImagePreset.objects.filter(
        id=preset_id,
        game=game,
        is_active=True,
    ).first()
    if preset is None:
        return {}, JsonResponse({'error': 'Selected image preset not found'}, status=404)

    try:
        image_path = preset.image.path
    except (ValueError, NotImplementedError):
        return {}, JsonResponse(
            {'error': 'Selected image preset has no local file'},
            status=400,
        )

    if not Path(image_path).is_file():
        return {}, JsonResponse(
            {'error': 'Selected image preset file is missing'},
            status=400,
        )

    return {
        'selected_image_preset_id': preset.id,
        'selected_image_path': image_path,
        'selected_image_url': preset.image.url,
        'selected_image_name': preset.name,
    }, None


def mark_image_override_used(job_settings: dict) -> None:
    """Update last-used metadata for a selected image override, if any."""

    media_settings = job_settings.get('_media', {})
    if not isinstance(media_settings, dict):
        return

    preset_id = media_settings.get('selected_image_preset_id')
    if not preset_id:
        return

    now = timezone.now()
    PostingImagePreset.objects.filter(id=preset_id).update(
        last_used_at=now,
        updated_at=now,
    )
