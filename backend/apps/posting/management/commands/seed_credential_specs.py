"""Seed CredentialSpec records from code-level presets.

Creates DB CredentialSpec entries for all games/variants defined in presets.py.
Existing specs are updated (fields + format_templates), not duplicated.

Usage:
    python manage.py seed_credential_specs           # dry-run (show what would happen)
    python manage.py seed_credential_specs --apply    # actually create/update
"""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand

from apps.inventory.models import Game
from apps.posting.models import CredentialSpec, GameVariant
from apps.posting.services.pool.presets import CREDENTIAL_PRESETS

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Seed CredentialSpec records from code-level presets."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually create/update specs. Without this flag, only shows a dry-run.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        if not apply:
            self.stdout.write(self.style.WARNING("DRY RUN — pass --apply to persist changes\n"))

        # Cache games by slug
        games = {g.slug: g for g in Game.objects.all()}
        # Cache variants by (game_id, slug)
        variants = {}
        for v in GameVariant.objects.select_related("game").all():
            variants[(v.game_id, v.slug)] = v

        stats = {"created": 0, "updated": 0, "skipped": 0}

        for preset_key, (name, fields, format_templates) in CREDENTIAL_PRESETS.items():
            if preset_key == "_default":
                # _default is a code-only fallback, not tied to a specific game
                self.stdout.write(f"  SKIP  {preset_key} (code-level fallback only)")
                stats["skipped"] += 1
                continue

            game_slug, variant_slug = _parse_preset_key(preset_key)
            game = games.get(game_slug)

            if not game:
                self.stdout.write(
                    self.style.WARNING(f"  SKIP  {preset_key} — game '{game_slug}' not in DB")
                )
                stats["skipped"] += 1
                continue

            variant = None
            if variant_slug:
                variant = variants.get((game.id, variant_slug))
                if not variant:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  SKIP  {preset_key} — variant '{variant_slug}' not in DB for {game_slug}"
                        )
                    )
                    stats["skipped"] += 1
                    continue

            # Find or create
            if variant:
                existing = CredentialSpec.objects.filter(variant=variant).first()
            else:
                existing = CredentialSpec.objects.filter(
                    game=game, variant__isnull=True
                ).first()

            if existing:
                changed = (
                    existing.fields != fields
                    or existing.format_templates != format_templates
                    or existing.name != name
                )
                if changed:
                    if apply:
                        existing.name = name
                        existing.fields = fields
                        existing.format_templates = format_templates
                        existing.is_active = True
                        existing.save()
                    self.stdout.write(
                        self.style.SUCCESS(f"  UPDATE  {preset_key} -> CredentialSpec #{existing.id}")
                    )
                    stats["updated"] += 1
                else:
                    self.stdout.write(f"  OK      {preset_key} -> CredentialSpec #{existing.id} (no changes)")
                    stats["skipped"] += 1
            else:
                if apply:
                    spec = CredentialSpec.objects.create(
                        game=game,
                        variant=variant,
                        name=name,
                        fields=fields,
                        format_templates=format_templates,
                        is_active=True,
                    )
                    self.stdout.write(
                        self.style.SUCCESS(f"  CREATE  {preset_key} -> CredentialSpec #{spec.id}")
                    )
                else:
                    self.stdout.write(
                        self.style.SUCCESS(f"  CREATE  {preset_key} -> (dry-run)")
                    )
                stats["created"] += 1

        self.stdout.write("")
        self.stdout.write(
            f"Done: {stats['created']} created, {stats['updated']} updated, {stats['skipped']} skipped"
        )
        if not apply:
            self.stdout.write(self.style.WARNING("Run with --apply to persist."))


def _parse_preset_key(key: str) -> tuple[str, str | None]:
    """Parse 'game-slug:variant-slug' or 'game-slug' into components."""
    if ":" in key:
        game_slug, variant_slug = key.split(":", 1)
        return game_slug, variant_slug
    return key, None
