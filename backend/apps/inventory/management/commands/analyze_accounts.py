"""Analyze OwnedProduct accounts from a login list and export detailed JSON.

Output structure per account:
  login, game, status, purchase_price, currency, purchased_at,
  orders: [{order_id, sold_price, sold_at, order_status, platform}],
  listing: {listing_id, platform, price, status, listed_at} | null

Usage:
    python manage.py analyze_accounts --input tmp/350supersellaccounts.txt
    python manage.py analyze_accounts --input tmp/350supersellaccounts.txt --output tmp/analysis.json
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.inventory.models import OwnedProduct


class Command(BaseCommand):
    help = 'Analyze OwnedProduct accounts from a login list'

    def add_arguments(self, parser):
        parser.add_argument('--input', '-i', required=True)
        parser.add_argument('--output', '-o', default='')

    def handle(self, *args, **options):
        input_path = Path(options['input'])
        if not input_path.exists():
            raise CommandError(f'Input file not found: {input_path}')

        output_path = options['output']
        if not output_path:
            from django.conf import settings
            date_str = timezone.now().strftime('%Y-%m-%d_%H%M')
            output_path = str(
                settings.ROOT_DIR / 'tmp' / f'accounts_analysis_{date_str}.json'
            )
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        logins = [
            l.strip() for l in input_path.read_text(encoding='utf-8').splitlines()
            if l.strip() and not l.startswith('#')
        ]
        self.stdout.write(f'Analyzing {len(logins)} logins...')

        # Bulk fetch owned products
        products_by_login = {}
        for op in (
            OwnedProduct.objects
            .filter(login__in=logins)
            .select_related('category', 'game')
            .prefetch_related(
                'orders__integration_account',
                'listing_owned_products__listing__integration_account',
            )
        ):
            products_by_login.setdefault(op.login, []).append(op)

        results = []
        stats = {
            'total': len(logins),
            'not_found': 0,
            'multiple_found': 0,
            'found': 0,
        }

        for login in logins:
            matches = products_by_login.get(login, [])

            if not matches:
                stats['not_found'] += 1
                results.append({'login': login, 'outcome': 'not_found'})
                continue

            if len(matches) > 1:
                stats['multiple_found'] += 1
                results.append({
                    'login': login,
                    'outcome': 'multiple_found',
                    'matches': [
                        {
                            'id': p.id,
                            'category': p.category.title,
                            'game': p.game.name if p.game_id else None,
                            'status': p.status,
                        }
                        for p in matches
                    ],
                })
                continue

            stats['found'] += 1
            op = matches[0]

            # Orders
            orders = []
            for order in op.orders.all():
                platform = (
                    order.integration_account.provider
                    if order.integration_account_id else None
                )
                orders.append({
                    'order_id': order.store_order_id,
                    'sold_price': float(order.price) if order.price is not None else None,
                    'currency': order.currency,
                    'sold_at': order.sold_at.strftime('%Y-%m-%d %H:%M:%S') if order.sold_at else None,
                    'order_status': order.status,
                    'platform': platform,
                })

            # Active listing (most recent non-removed)
            listing = None
            for lop in op.listing_owned_products.all():
                lst = lop.listing
                if lst.removed_at is None:
                    platform = (
                        lst.integration_account.provider
                        if lst.integration_account_id else None
                    )
                    listing = {
                        'listing_id': lst.store_listing_id,
                        'platform': platform,
                        'price': float(lst.price) if lst.price is not None else None,
                        'currency': lst.currency,
                        'status': lst.status,
                        'listed_at': lst.listed_at.strftime('%Y-%m-%d %H:%M:%S') if lst.listed_at else None,
                    }
                    break

            results.append({
                'login': op.login,
                'category': op.category.title if op.category_id else None,
                'game': op.game.name if op.game_id else None,
                'status': op.status,
                'purchase_price': float(op.price) if op.price is not None else None,
                'currency': op.currency,
                'purchased_at': op.purchased_at.strftime('%Y-%m-%d %H:%M:%S') if op.purchased_at else None,
                'orders': orders,
                'listing': listing,
            })

        output = {
            'analyzed_at': timezone.now().isoformat(),
            'input_file': str(input_path),
            'stats': stats,
            'accounts': results,
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        self.stdout.write(self.style.SUCCESS(
            f'Done. found={stats["found"]}, '
            f'not_found={stats["not_found"]}, '
            f'multiple={stats["multiple_found"]}\n'
            f'Output: {output_path}'
        ))
