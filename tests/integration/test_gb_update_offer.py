"""Test Gameboost PATCH /account-offers/{id} endpoint.

Builds a client from Django DB (gameboost-store4gamers),
picks the first listed offer, sends a harmless private_note update,
and logs full raw response details (status, headers, body).

Usage (from project root):
    python tests/integration/test_gb_update_offer.py
    python tests/integration/test_gb_update_offer.py --offer-id 4406148
    python tests/integration/test_gb_update_offer.py --dry-run
"""

import argparse
import json
import os
import sys

# ── Bootstrap Django ────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
BACKEND_DIR = os.path.join(PROJECT_ROOT, 'backend')

sys.path.insert(0, BACKEND_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

import django  # noqa: E402
django.setup()

from apps.integrations.models import IntegrationAccount  # noqa: E402
from apps.integrations.providers.registry import get_or_build_client  # noqa: E402

ACCOUNT_SLUG = 'gameboost-store4gamers'

# ── Raw response capture ───────────────────────────────────────────
_captured_responses = []


def install_transport_hook(facade):
    """Monkey-patch the transport to capture raw responses."""
    transport = facade._exec._transport
    if not transport:
        print("WARNING: no transport found on facade, raw logging disabled")
        return

    original_request = transport.request

    def hooked_request(method, url, **kwargs):
        resp = original_request(method, url, **kwargs)
        _captured_responses.append({
            'method': str(method),
            'url': url,
            'status_code': resp.status_code,
            'headers': dict(resp.headers),
            'body_preview': resp.body[:2000].decode('utf-8', errors='replace'),
        })
        return resp

    transport.request = hooked_request


def print_raw_capture(label: str):
    """Print and clear the last captured raw response."""
    if not _captured_responses:
        print(f"\n  [no raw response captured for {label}]")
        return

    raw = _captured_responses.pop()
    print(f"\n{'-'*60}")
    print(f"  RAW: {label}")
    print(f"{'-'*60}")
    print(f"  {raw['method']} {raw['url']}")
    print(f"  Status: {raw['status_code']}")
    print(f"\n  -- Response Headers --")
    for k, v in sorted(raw['headers'].items()):
        print(f"    {k}: {v}")
    print(f"\n  -- Response Body (first 2000 chars) --")
    try:
        body_json = json.loads(raw['body_preview'])
        print(f"    {json.dumps(body_json, indent=4, default=str)[:3000]}")
    except (json.JSONDecodeError, ValueError):
        print(f"    {raw['body_preview']}")


# ── Display helpers ─────────────────────────────────────────────────
def pp(label: str, obj):
    if isinstance(obj, dict):
        print(f"{label}: {json.dumps(obj, indent=2, default=str)}")
    else:
        print(f"{label}: {obj}")


def print_offer(offer):
    for field in ('id', 'title', 'slug', 'status', 'price', 'price_usd', 'description'):
        val = getattr(offer, field, None)
        if val is not None:
            print(f"  {field}: {val!r}")
    creds = getattr(offer, 'credentials', None)
    if creds:
        print(f"  credentials: {creds}")
    params = getattr(offer, 'parameters', None)
    if params:
        print(f"  parameters: {json.dumps(params, indent=4, default=str)}")


def print_result(label: str, result):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    pp("  ok", result.ok)
    pp("  status_code", result.status_code)
    if result.meta:
        pp("  meta", result.meta)
    if result.ok:
        print_offer(result.data)
    else:
        err = result.error
        pp("  error.category", err.category)
        pp("  error.message", err.message)
        pp("  error.status_code", err.status_code)
        pp("  error.is_retryable", err.is_retryable)
        if err.details:
            pp("  error.details", err.details)

    # Always print raw response after SDK result
    print_raw_capture(label)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offer-id', type=str, default=None,
                        help='Specific offer ID. If omitted, picks the first listed offer.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Only list offers, do not send update.')
    args = parser.parse_args()

    # ── 1. Build client from DB ──────────────────────────────────────
    account = IntegrationAccount.objects.select_related('credential').get(
        slug=ACCOUNT_SLUG, is_active=True,
    )
    if not hasattr(account, 'credential') or not account.credential.is_active:
        sys.exit(f'ERROR: {ACCOUNT_SLUG} has no active credentials')

    facade = get_or_build_client('gameboost', account.credential)
    install_transport_hook(facade)
    print(f'Client built for: {ACCOUNT_SLUG}\n')

    # ── 2. Determine offer ID ────────────────────────────────────────
    offer_id = args.offer_id

    if not offer_id:
        print('Fetching listed offers...')
        list_result = facade.list_offers(params={'status': 'listed', 'per_page': 5})

        if not list_result.ok:
            print_result('LIST OFFERS (failed)', list_result)
            return

        offers = list_result.data
        print(f'Found {len(offers)} listed offers:')
        for i, o in enumerate(offers):
            print(f'  [{i}] id={o.id}  title={getattr(o, "title", "?")!r}  price={getattr(o, "price", "?")}')

        if list_result.meta:
            pp('\nList meta', list_result.meta)

        # Print raw for list too
        print_raw_capture('LIST /account-offers')

        if not offers:
            print('No listed offers found.')
            return

        offer_id = str(offers[0].id)
        print(f'\nSelected offer_id={offer_id}')

    if args.dry_run:
        print('\n--dry-run: stopping before update')
        return

    # ── 3. GET current state ─────────────────────────────────────────
    get_result = facade.get_offer(offer_id)
    print_result(f'GET /account-offers/{offer_id}', get_result)

    # ── 4. PATCH update ──────────────────────────────────────────────
    payload = {
        'private_note': 'SDK update_account_offer test - safe to remove',
    }
    print(f'\nSending PATCH with payload: {json.dumps(payload, indent=2)}')

    update_result = facade.update_offer(offer_id, payload)
    print_result(f'PATCH /account-offers/{offer_id}', update_result)


if __name__ == '__main__':
    main()
