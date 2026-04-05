"""Export Gameboost instant offers without OwnedProduct links.

Queries Listing table for Gameboost provider, is_instant=True,
with no ListingOwnedProduct M2M records. Writes raw_data to JSON.

Usage:
    python manage.py shell -c "exec(open('../scripts/export_unlinked_gameboost_offers.py').read())"
    # or via Django setup:
    python scripts/export_unlinked_gameboost_offers.py
"""

import json
import os
import sys

# Django setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

import django
django.setup()

from apps.listings.models import Listing

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), '..', 'unlinked_gameboost_offers.json')


def run():
    qs = Listing.objects.filter(
        integration_account__provider='gameboost',
        is_instant=True,
    ).exclude(
        listing_owned_products__isnull=False,
    ).select_related('integration_account', 'game')

    results = []
    for listing in qs:
        results.append({
            'store_listing_id': listing.store_listing_id,
            'title': listing.title,
            'status': listing.status,
            'price': str(listing.price),
            'currency': listing.currency,
            'game': listing.game.name if listing.game else None,
            'game_id': listing.game_id,
            'raw_data': listing.raw_data,
        })

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    print(f'Unlinked Gameboost instant offers: {len(results)}')
    print(f'Written to: {OUTPUT_FILE}')


run()
