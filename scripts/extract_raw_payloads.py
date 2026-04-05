"""Extract raw_data from Orders and Listings where category=accounts & is_instant=True.

Outputs two JSON files under tmp/raw_payloads/:
  - orders_raw.json
  - listings_raw.json

Usage (from project root):
    python scripts/extract_raw_payloads.py
"""

import json
import os
import sys

# ── Bootstrap Django ────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, 'backend')

sys.path.insert(0, BACKEND_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

import django  # noqa: E402
django.setup()

from apps.orders.models import Order  # noqa: E402
from apps.listings.models import Listing  # noqa: E402

# ── Config ──────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(PROJECT_ROOT, 'tmp', 'raw_payloads')
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Orders ──────────────────────────────────────────────────────────
orders_qs = Order.objects.filter(
    product_category='accounts',
    is_instant=True,
).exclude(raw_data__isnull=True)

orders_data = []
for o in orders_qs.iterator():
    orders_data.append({
        'id': o.id,
        'store_order_id': o.store_order_id,
        'status': o.status,
        'raw_data': o.raw_data,
    })

orders_file = os.path.join(OUTPUT_DIR, 'orders_raw.json')
with open(orders_file, 'w', encoding='utf-8') as f:
    json.dump(orders_data, f, indent=2, ensure_ascii=False, default=str)

print(f'Orders: {len(orders_data)} kayit → {orders_file}')

# ── Listings ────────────────────────────────────────────────────────
listings_qs = Listing.objects.filter(
    product_category='accounts',
    is_instant=True,
).exclude(raw_data__isnull=True)

listings_data = []
for l in listings_qs.iterator():
    listings_data.append({
        'id': l.id,
        'store_listing_id': l.store_listing_id,
        'status': l.status,
        'raw_data': l.raw_data,
    })

listings_file = os.path.join(OUTPUT_DIR, 'listings_raw.json')
with open(listings_file, 'w', encoding='utf-8') as f:
    json.dump(listings_data, f, indent=2, ensure_ascii=False, default=str)

print(f'Listings: {len(listings_data)} kayit → {listings_file}')

# ── Summary ─────────────────────────────────────────────────────────
print(f'\nDosyalar: {OUTPUT_DIR}')
