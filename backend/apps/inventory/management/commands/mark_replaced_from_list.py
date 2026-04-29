"""Mark OwnedProducts as REPLACED from a login list.

Input file format (one entry per line, game is optional):
    login@example.com
    login@example.com<TAB>Counter-Strike 2
    login@example.com,Fortnite

Lookup logic:
  - Game provided  → match by (login + game__name), fallback to (login + category__title)
  - Game omitted   → match by login only
  - Multiple hits  → warn, skip, log
  - 0 hits         → not_found, log
  - sold / multiple_sold → skip, log
  - draft / listed → set REPLACED
    * listed: status updated but active listing NOT removed — flagged in output

Flags:
    --dry-run   (default) Show what would change, write nothing
    --execute   Apply changes

Usage:
    python manage.py mark_replaced_from_list --input /tmp/accounts.txt
    python manage.py mark_replaced_from_list --input /tmp/accounts.txt --execute
    python manage.py mark_replaced_from_list --input /tmp/accounts.txt --execute --output /tmp/results.json
"""

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.inventory.enums import OwnedProductStatus
from apps.inventory.models import OwnedProduct


_SKIP_STATUSES = {OwnedProductStatus.SOLD, OwnedProductStatus.MULTIPLE_SOLD}
_REPLACE_STATUSES = {OwnedProductStatus.DRAFT, OwnedProductStatus.LISTED}


def _parse_line(line: str) -> tuple[str, str | None]:
    """Return (login, game_or_None) from a single input line."""
    line = line.strip()
    if not line or line.startswith('#'):
        return '', None

    # Tab-separated
    if '\t' in line:
        parts = line.split('\t', 1)
        return parts[0].strip(), parts[1].strip() or None

    # Comma-separated — but only split if the second part looks like a game
    # (no @ to avoid splitting emails with commas)
    if ',' in line:
        parts = line.split(',', 1)
        left, right = parts[0].strip(), parts[1].strip()
        if right and '@' not in right:
            return left, right or None

    return line, None


def _find_products(login: str, game: str | None):
    """Return queryset for (login, game) pair."""
    qs = OwnedProduct.objects.select_related('category', 'game')

    if game:
        # Try game name first
        by_game = qs.filter(login=login, game__name__iexact=game)
        if by_game.exists():
            return by_game
        # Fallback: category title
        by_cat = qs.filter(login=login, category__title__iexact=game)
        if by_cat.exists():
            return by_cat
        # Nothing matched with game hint — return empty
        return OwnedProduct.objects.none()

    return qs.filter(login=login)


class Command(BaseCommand):
    help = 'Mark OwnedProducts as REPLACED from a login list (dry-run by default)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--input', '-i',
            required=True,
            help='Path to the input text file (one login per line)',
        )
        parser.add_argument(
            '--output', '-o',
            default='',
            help='Path for the JSON results file (default: tmp/mark_replaced_<date>.json)',
        )
        parser.add_argument(
            '--execute',
            action='store_true',
            default=False,
            help='Actually apply changes (default is dry-run)',
        )

    def handle(self, *args, **options):
        input_path = Path(options['input'])
        execute = options['execute']
        output_path = options['output']

        if not input_path.exists():
            raise CommandError(f'Input file not found: {input_path}')

        if not output_path:
            from django.conf import settings
            date_str = timezone.now().strftime('%Y-%m-%d_%H%M')
            output_path = str(
                settings.ROOT_DIR / 'tmp' / f'mark_replaced_{date_str}.json'
            )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        mode = 'EXECUTE' if execute else 'DRY-RUN'
        self.stdout.write(f'Mode: {mode}')

        lines = input_path.read_text(encoding='utf-8').splitlines()
        self.stdout.write(f'Input lines: {len(lines)}')

        results = []
        stats = {
            'total_lines': len(lines),
            'skipped_blank': 0,
            'not_found': 0,
            'multiple_found': 0,
            'skipped_sold': 0,
            'replaced': 0,
            'replaced_was_listed': 0,
            'errors': 0,
        }

        ids_to_update = []

        for raw_line in lines:
            login, game = _parse_line(raw_line)

            if not login:
                stats['skipped_blank'] += 1
                continue

            try:
                qs = _find_products(login, game)
                count = qs.count()
            except Exception as exc:
                stats['errors'] += 1
                results.append({
                    'login': login,
                    'game': game,
                    'outcome': 'error',
                    'detail': str(exc),
                })
                continue

            if count == 0:
                stats['not_found'] += 1
                results.append({
                    'login': login,
                    'game': game,
                    'outcome': 'not_found',
                })
                continue

            if count > 1:
                stats['multiple_found'] += 1
                matches = [
                    {
                        'id': p.id,
                        'category': p.category.title,
                        'game': p.game.name if p.game_id else None,
                        'status': p.status,
                    }
                    for p in qs[:10]
                ]
                results.append({
                    'login': login,
                    'game': game,
                    'outcome': 'multiple_found',
                    'detail': f'{count} records found — skipped, manual review needed',
                    'matches': matches,
                })
                self.stdout.write(
                    self.style.WARNING(f'  MULTIPLE ({count}): {login!r}')
                )
                continue

            product = qs.first()

            if product.status in _SKIP_STATUSES:
                stats['skipped_sold'] += 1
                results.append({
                    'login': login,
                    'game': game,
                    'outcome': 'skipped_sold',
                    'id': product.id,
                    'category': product.category.title,
                    'status': product.status,
                })
                continue

            if product.status not in _REPLACE_STATUSES:
                # already replaced, banned, lost, etc.
                results.append({
                    'login': login,
                    'game': game,
                    'outcome': 'skipped_already',
                    'id': product.id,
                    'category': product.category.title,
                    'status': product.status,
                    'detail': f'Status is already {product.status!r}, no change needed',
                })
                continue

            was_listed = product.status == OwnedProductStatus.LISTED
            stats['replaced'] += 1
            if was_listed:
                stats['replaced_was_listed'] += 1

            ids_to_update.append(product.id)
            results.append({
                'login': login,
                'game': game,
                'outcome': 'replaced' if not was_listed else 'replaced_was_listed',
                'id': product.id,
                'category': product.category.title,
                'game_name': product.game.name if product.game_id else None,
                'previous_status': product.status,
                **(
                    {'warning': 'Had active listing — listing NOT removed, check marketplace'}
                    if was_listed else {}
                ),
            })

            if was_listed:
                self.stdout.write(
                    self.style.WARNING(
                        f'  LISTED→REPLACED (listing still active!): '
                        f'id={product.id} {login!r}'
                    )
                )

        # Apply changes
        if execute and ids_to_update:
            with transaction.atomic():
                updated = OwnedProduct.objects.filter(id__in=ids_to_update).update(
                    status=OwnedProductStatus.REPLACED
                )
            self.stdout.write(self.style.SUCCESS(f'Updated {updated} records → REPLACED'))
        elif not execute and ids_to_update:
            self.stdout.write(
                self.style.NOTICE(
                    f'[DRY-RUN] Would update {len(ids_to_update)} records → REPLACED'
                )
            )

        output = {
            'mode': mode,
            'executed_at': timezone.now().isoformat(),
            'input_file': str(input_path),
            'stats': stats,
            'results': results,
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        self.stdout.write('\n── Summary ──────────────────────────────')
        self.stdout.write(f"  not_found:        {stats['not_found']}")
        self.stdout.write(f"  multiple_found:   {stats['multiple_found']}  ← manual review")
        self.stdout.write(f"  skipped_sold:     {stats['skipped_sold']}")
        self.stdout.write(
            f"  replaced:         {stats['replaced']}  "
            f"(of which listed: {stats['replaced_was_listed']})"
        )
        self.stdout.write(f"  errors:           {stats['errors']}")
        self.stdout.write(f"  Output:           {output_path}")
