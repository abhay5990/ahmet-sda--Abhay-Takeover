"""Populate FeeRule table with known marketplace fee structures.

Usage:
    python manage.py populate_fee_rules
    python manage.py populate_fee_rules --dry-run
    python manage.py populate_fee_rules --clear   # delete existing rules and recreate
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.inventory.models import Game
from apps.orders.enums import FeeType
from apps.orders.models import FeeRule


# ── Effective date ───────────────────────────────────────────────────
# All rules are effective from this date. Set far enough in the past
# so that historical orders also match.
EFFECTIVE_FROM = date(2024, 1, 1)


def _game(slug: str) -> Game | None:
    """Lookup Game by slug. Returns None if not found (rule is skipped)."""
    try:
        return Game.objects.get(slug=slug)
    except Game.DoesNotExist:
        return None


def _build_rules() -> list[dict]:
    """Return all FeeRule definitions as a list of dicts."""
    rules = []

    # ══════════════════════════════════════════════════════════════════
    #  GAMEBOOST — Mythic Rank
    # ══════════════════════════════════════════════════════════════════

    gb = 'gameboost'

    # Category-level defaults
    gb_defaults = [
        # (category, percent, flat_fee, note)
        ('accounts', '10.00', '0.99', 'Mythic rank — accounts default'),
        ('items',    '15.00', '0.29', 'Mythic rank — items/skins'),
        ('currency', '5.00',  '0.00', 'Mythic rank — currency'),
        ('top_up',   '5.00',  '0.00', 'Mythic rank — top-ups'),
    ]
    for cat, pct, flat, note in gb_defaults:
        rules.append({
            'marketplace': gb,
            'fee_type': FeeType.SALE,
            'product_category': cat,
            'game': None,
            'fee_percent': Decimal(pct),
            'flat_fee': Decimal(flat),
            'flat_fee_currency': 'EUR',
            'note': note,
        })

    # Game-specific overrides (accounts)
    gb_game_overrides = [
        # (slug, percent, note)
        ('clash-of-clans',     '20.00', 'Fixed — rank-independent'),
        ('fortnite',           '20.00', 'Fixed — rank-independent'),
        ('grand-theft-auto-5', '25.00', 'Fixed — rank-independent'),
    ]
    for slug, pct, note in gb_game_overrides:
        game = _game(slug)
        if not game:
            continue
        rules.append({
            'marketplace': gb,
            'fee_type': FeeType.SALE,
            'product_category': 'accounts',
            'game': game,
            'fee_percent': Decimal(pct),
            'flat_fee': Decimal('0.99'),
            'flat_fee_currency': 'EUR',
            'note': f'Gameboost game override: {slug} — {note}',
        })

    # ══════════════════════════════════════════════════════════════════
    #  ELDORADO
    # ══════════════════════════════════════════════════════════════════

    eld = 'eldorado'

    # Category-level defaults
    eld_defaults = [
        ('currency',  '5.00',  'Currency default'),
        ('top_up',    '0.00',  'Top Up & Gift Cards — 0%'),
        ('gift_card', '0.00',  'Top Up & Gift Cards — 0%'),
        ('items',     '10.00', 'Items default'),
        ('accounts',  '10.00', 'Accounts default'),
    ]
    for cat, pct, note in eld_defaults:
        rules.append({
            'marketplace': eld,
            'fee_type': FeeType.SALE,
            'product_category': cat,
            'game': None,
            'fee_percent': Decimal(pct),
            'flat_fee': Decimal('0'),
            'flat_fee_currency': 'USD',
            'note': f'Eldorado — {note}',
        })

    # Currency — low fee games (1.5%)
    for slug in ['old-school-runescape', 'world-of-warcraft', 'wow-classic']:
        game = _game(slug)
        if not game:
            continue
        rules.append({
            'marketplace': eld,
            'fee_type': FeeType.SALE,
            'product_category': 'currency',
            'game': game,
            'fee_percent': Decimal('1.50'),
            'flat_fee': Decimal('0'),
            'flat_fee_currency': 'USD',
            'note': f'Eldorado currency override: {slug} — 1.5%',
        })

    # Currency — 3% games
    for slug in ['lost-ark', 'warframe', 'new-world']:
        game = _game(slug)
        if not game:
            continue
        rules.append({
            'marketplace': eld,
            'fee_type': FeeType.SALE,
            'product_category': 'currency',
            'game': game,
            'fee_percent': Decimal('3.00'),
            'flat_fee': Decimal('0'),
            'flat_fee_currency': 'USD',
            'note': f'Eldorado currency override: {slug} — 3%',
        })

    # Items — OSRS 3%, RS3 5%
    items_overrides = [
        ('old-school-runescape', '3.00'),
        ('runescape-3', '5.00'),
    ]
    for slug, pct in items_overrides:
        game = _game(slug)
        if not game:
            continue
        rules.append({
            'marketplace': eld,
            'fee_type': FeeType.SALE,
            'product_category': 'items',
            'game': game,
            'fee_percent': Decimal(pct),
            'flat_fee': Decimal('0'),
            'flat_fee_currency': 'USD',
            'note': f'Eldorado items override: {slug} — {pct}%',
        })

    # Premium accounts (20-30%)
    premium_accounts = [
        ('call-of-duty',       '20.00'),
        ('fortnite',           '20.00'),
        ('rainbow-six-siege',  '20.00'),
        ('grand-theft-auto-5', '30.00'),
    ]
    for slug, pct in premium_accounts:
        game = _game(slug)
        if not game:
            continue
        rules.append({
            'marketplace': eld,
            'fee_type': FeeType.SALE,
            'product_category': 'accounts',
            'game': game,
            'fee_percent': Decimal(pct),
            'flat_fee': Decimal('0'),
            'flat_fee_currency': 'USD',
            'note': f'Eldorado premium accounts: {slug} — {pct}%',
        })

    # ══════════════════════════════════════════════════════════════════
    #  PLAYERAUCTIONS
    # ══════════════════════════════════════════════════════════════════

    pa = 'playerauctions'

    # Category-level defaults
    # Source: https://support.playerauctions.com/hc/en-us/articles/115008180648
    pa_defaults = [
        # (category, percent, flat_fee, note)
        ('currency', '9.99',  '0.99', 'Currency default'),
        ('items',    '9.99',  '0.99', 'Items default'),
        ('accounts', '12.99', '0.99', 'Accounts default'),
        ('top_up',   '4.99',  '0.99', 'Top Up default'),
    ]
    for cat, pct, flat, note in pa_defaults:
        rules.append({
            'marketplace': pa,
            'fee_type': FeeType.SALE,
            'product_category': cat,
            'game': None,
            'fee_percent': Decimal(pct),
            'flat_fee': Decimal(flat),
            'flat_fee_currency': 'USD',
            'note': f'PlayerAuctions — {note}',
        })

    return rules


class Command(BaseCommand):
    help = 'Populate FeeRule table with Eldorado, Gameboost & PlayerAuctions fee structures'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview only, do not write to DB',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete existing rules and recreate from scratch',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        clear = options['clear']

        if clear and not dry_run:
            deleted, _ = FeeRule.objects.all().delete()
            self.stdout.write(f'Deleted rules: {deleted}')

        definitions = _build_rules()
        created = 0
        skipped = 0

        for defn in definitions:
            lookup = {
                'marketplace': defn['marketplace'],
                'fee_type': defn['fee_type'],
                'product_category': defn['product_category'],
                'game': defn['game'],
            }

            if dry_run:
                game_name = defn['game'].name if defn['game'] else '(all)'
                self.stdout.write(
                    f"  {defn['marketplace']:15} | {defn['product_category'] or '(all)':10} "
                    f"| {game_name:25} | {defn['fee_percent']:>6}% "
                    f"+ {defn['flat_fee']} {defn['flat_fee_currency']} "
                    f"| {defn['note']}"
                )
                created += 1
                continue

            # Skip if same combination already exists (idempotent)
            existing = FeeRule.objects.filter(
                **lookup,
                effective_until__isnull=True,  # active rule
            ).first()
            if existing:
                skipped += 1
                continue

            FeeRule.objects.create(
                **lookup,
                fee_percent=defn['fee_percent'],
                flat_fee=defn['flat_fee'],
                flat_fee_currency=defn['flat_fee_currency'],
                effective_from=EFFECTIVE_FROM,
                effective_until=None,
                note=defn['note'],
            )
            created += 1

        prefix = '[DRY-RUN] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}{created} rule(s) created, {skipped} skipped (already exist).'
        ))
