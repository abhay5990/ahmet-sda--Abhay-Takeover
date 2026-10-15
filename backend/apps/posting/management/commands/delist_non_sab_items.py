"""Delist non-SAB Eldorado offers that were incorrectly posted as SAB items.

Usage:
  python manage.py delist_non_sab_items --dry-run
  python manage.py delist_non_sab_items --execute
  python manage.py delist_non_sab_items --execute --limit 100
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.posting.services.dropship.non_sab_cleanup import cleanup_non_sab_item_listings


class Command(BaseCommand):
    help = "Delist steal-a-brainrot GameBoost offers whose Eldorado gameId is not 259"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report non-SAB listings without deleting (default if --execute omitted)",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Actually archive non-SAB GameBoost offers and mark DropshipProducts deleted",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Max number of non-SAB DropshipProducts to delist",
        )

    def handle(self, *args, **options):
        dry_run = not options["execute"]
        if options["dry_run"]:
            dry_run = True
        limit = options["limit"]

        result = cleanup_non_sab_item_listings(dry_run=dry_run, limit=limit)
        mode = "DRY-RUN" if result.dry_run else "EXECUTE"
        self.stdout.write(
            f"[{mode}] scanned={result.scanned} sab_kept={result.sab_kept} "
            f"unknown_game_id={result.unknown_game_id} non_sab_found={result.non_sab_found} "
            f"delisted={result.delisted} failed={result.failed}"
        )
        if result.non_sab_offer_ids:
            preview = ", ".join(result.non_sab_offer_ids[:20])
            self.stdout.write(f"Non-SAB GB offer IDs ({len(result.non_sab_offer_ids)}): {preview}...")
        if result.errors:
            for key, err in list(result.errors.items())[:20]:
                self.stderr.write(self.style.ERROR(f"  {key}: {err}"))
        if result.failed:
            raise SystemExit(1)
