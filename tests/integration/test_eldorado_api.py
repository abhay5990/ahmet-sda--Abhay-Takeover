"""Test Eldorado API endpoints via SDK.

Builds a client from Django DB, runs read-only tests by default.
Logs full raw response details (status, headers, body) for debugging.

Usage (from project root):
    python tests/integration/test_eldorado_api.py
    python tests/integration/test_eldorado_api.py --account eldorado-store4gamers
    python tests/integration/test_eldorado_api.py --test offers
    python tests/integration/test_eldorado_api.py --test orders
    python tests/integration/test_eldorado_api.py --test upload --image path/to/image.png
    python tests/integration/test_eldorado_api.py --test all
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


# ── Raw response capture ───────────────────────────────────────────
_captured_responses = []


DEFAULT_UA = ""


def install_transport_hook(facade, *, inject_ua: bool = False):
    """Monkey-patch the transport to capture raw responses and optionally inject UA."""
    transport = facade._exec._transport
    if not transport:
        print("WARNING: no transport found on facade, raw logging disabled")
        return

    original_request = transport.request

    def hooked_request(method, url, **kwargs):
        if inject_ua:
            headers = kwargs.get('headers') or {}
            headers.setdefault('User-Agent', DEFAULT_UA)
            headers.setdefault('Accept', 'application/json, text/plain, */*')
            headers.setdefault('Accept-Language', 'en-US,en;q=0.9')
            headers.setdefault('Origin', 'https://www.eldorado.gg')
            headers.setdefault('Referer', 'https://www.eldorado.gg/')
            kwargs['headers'] = headers
        resp = original_request(method, url, **kwargs)
        _captured_responses.append({
            'method': str(method),
            'url': url,
            'status_code': resp.status_code,
            'headers': dict(resp.headers),
            'body_preview': resp.body[:3000].decode('utf-8', errors='replace'),
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
    print(f"\n  -- Response Body (first 3000 chars) --")
    try:
        body_json = json.loads(raw['body_preview'])
        print(f"    {json.dumps(body_json, indent=4, default=str)[:3000]}")
    except (json.JSONDecodeError, ValueError):
        print(f"    {raw['body_preview'][:3000]}")


# ── Display helpers ─────────────────────────────────────────────────
def pp(label: str, obj):
    if isinstance(obj, dict):
        print(f"{label}: {json.dumps(obj, indent=2, default=str)}")
    else:
        print(f"{label}: {obj}")


def print_result(label: str, result, show_data=True):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    pp("  ok", result.ok)
    pp("  status_code", result.status_code)
    if result.meta:
        pp("  meta", result.meta)
    if result.ok and show_data:
        data = result.data
        if hasattr(data, 'model_dump'):
            dumped = data.model_dump()
            print(f"  data: {json.dumps(dumped, indent=2, default=str)[:2000]}")
        elif isinstance(data, list):
            print(f"  data ({len(data)} items): {data[:5]}")
        else:
            print(f"  data: {data}")
    elif not result.ok:
        err = result.error
        pp("  error.category", err.category)
        pp("  error.message", err.message[:500])
        pp("  error.status_code", err.status_code)
        pp("  error.is_retryable", err.is_retryable)
        if err.details:
            pp("  error.details", err.details)

    print_raw_capture(label)


# ── Test functions ──────────────────────────────────────────────────

def test_offer_state_counts(facade):
    """GET offer state counts (active, inactive, pending, suspended)."""
    print("\n\n" + "#" * 60)
    print("  TEST: Offer State Counts")
    print("#" * 60)

    result = facade.get_offer_state_counts()
    print_result("GET /offers/state-counts", result)
    return result.ok


def test_search_offers(facade):
    """GET search my offers (first page)."""
    print("\n\n" + "#" * 60)
    print("  TEST: Search My Offers")
    print("#" * 60)

    result = facade.search_my_offers(params={
        'state': 'Active',
        'pageNumber': 1,
        'pageSize': 5,
    })
    print_result("GET /offers/search (Active, page 1, size 5)", result)

    if result.ok and hasattr(result.data, 'items'):
        items = result.data.items
        print(f"\n  Found {len(items)} offers:")
        for i, offer in enumerate(items):
            title = getattr(offer, 'title', '?')
            offer_id = getattr(offer, 'id', '?')
            price = getattr(offer, 'price', '?')
            status = getattr(offer, 'state', getattr(offer, 'status', '?'))
            print(f"    [{i}] id={offer_id}  title={title!r}  price={price}  status={status}")

    return result.ok


def test_seller_orders(facade):
    """GET seller orders (first page)."""
    print("\n\n" + "#" * 60)
    print("  TEST: Seller Orders")
    print("#" * 60)

    result = facade.get_seller_orders(params={
        'pageNumber': 1,
        'pageSize': 5,
    })
    print_result("GET /orders/seller (page 1, size 5)", result)

    if result.ok and hasattr(result.data, 'items'):
        items = result.data.items
        print(f"\n  Found {len(items)} orders:")
        for i, order in enumerate(items):
            order_id = getattr(order, 'id', getattr(order, 'orderId', '?'))
            status = getattr(order, 'status', '?')
            price = getattr(order, 'price', '?')
            print(f"    [{i}] id={order_id}  status={status}  price={price}")

    return result.ok


def test_notifications(facade, page_size: int = 20, cursor: str | None = None):
    """GET notifications for the authenticated user."""
    print("\n\n" + "#" * 60)
    print("  TEST: Notifications")
    print("#" * 60)

    params: dict = {"pageSize": page_size}
    if cursor:
        params["cursor"] = cursor

    result = facade.get_notifications(params=params)
    print_result("GET /notifications/me", result)

    if result.ok and result.data:
        page = result.data
        print(f"\n  pageSize={page.pageSize}  pageDirection={page.pageDirection!r}")
        print(f"  cursor={page.cursor!r}")
        print(f"  previousPageCursor={page.previousPageCursor!r}")
        print(f"  nextPageCursor={page.nextPageCursor!r}")
        print(f"  results count: {len(page.results)}")

        for i, item in enumerate(page.results):
            n = item.notification
            custom = item.customNotification
            print(f"\n  [{i}] id={n.id!r}  type={n.type!r}  event={n.event!r}")
            print(f"       readStatus={n.notificationReadStatus!r}  recipientRole={n.recipientRole!r}")
            print(f"       date={n.notificationDate!r}")
            d = n.details
            print(f"       details.title={d.title!r}  buyer={d.buyerUsername!r}  seller={d.sellerUsername!r}")
            print(f"       details.price={d.price.amount} {d.price.currency}  game={d.gameCategoryTitle!r}")
            if n.customNotificationData:
                cnd = n.customNotificationData
                print(f"       customNotificationData.reason={cnd.reason!r}  orderId={cnd.orderId!r}")
                if cnd.additionalDetails:
                    print(f"       customNotificationData.additionalDetails={cnd.additionalDetails!r}")
            if custom:
                print(f"       customNotification (raw)={custom}")

    return result.ok


def test_upload_image(facade, image_path: str):
    """POST upload image."""
    print("\n\n" + "#" * 60)
    print("  TEST: Upload Image")
    print("#" * 60)

    if not os.path.exists(image_path):
        print(f"  ERROR: Image file not found: {image_path}")
        return False

    file_size = os.path.getsize(image_path)
    print(f"  File: {image_path}")
    print(f"  Size: {file_size:,} bytes")

    result = facade.upload_image(image_path)
    print_result(f"POST /files/me/Offer ({os.path.basename(image_path)})", result)
    return result.ok


# ── Main ────────────────────────────────────────────────────────────

def find_eldorado_account(slug=None):
    """Find an active Eldorado account from DB."""
    if slug:
        try:
            account = IntegrationAccount.objects.select_related('credential').get(
                slug=slug, is_active=True,
            )
            return account
        except IntegrationAccount.DoesNotExist:
            print(f"ERROR: Account '{slug}' not found or inactive")
            return None

    # Auto-find first active eldorado account
    accounts = IntegrationAccount.objects.select_related('credential').filter(
        provider='eldorado', is_active=True,
    )
    if not accounts.exists():
        print("ERROR: No active Eldorado accounts found in DB")
        return None

    print("Available Eldorado accounts:")
    for acc in accounts:
        has_cred = hasattr(acc, 'credential') and acc.credential.is_active
        print(f"  - {acc.slug} (name={acc.name}, has_credential={has_cred})")

    account = accounts.first()
    print(f"\nUsing: {account.slug}")
    return account


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--account', type=str, default=None,
                        help='Account slug (e.g. "eldorado-store4gamers"). Auto-detects if omitted.')
    parser.add_argument('--test', type=str, default='all',
                        choices=['all', 'offers', 'orders', 'counts', 'upload', 'notifications'],
                        help='Which test to run (default: all)')
    parser.add_argument('--cursor', type=str, default=None,
                        help='Pagination cursor for notifications test')
    parser.add_argument('--page-size', type=int, default=20,
                        help='Page size for notifications test (default: 20)')
    parser.add_argument('--image', type=str, default=None,
                        help='Image file path for upload test')
    parser.add_argument('--ua', action='store_true',
                        help='Inject browser-like User-Agent and headers into requests')
    args = parser.parse_args()

    # ── 1. Find account ────────────────────────────────────────────
    account = find_eldorado_account(args.account)
    if not account:
        sys.exit(1)

    if not hasattr(account, 'credential') or not account.credential.is_active:
        sys.exit(f'ERROR: {account.slug} has no active credentials')

    # ── 2. Build client ────────────────────────────────────────────
    facade = get_or_build_client('eldorado', account.credential)
    install_transport_hook(facade, inject_ua=args.ua)
    print(f"Client built for: {account.slug}")
    print(f"Provider: eldorado")
    if args.ua:
        print(f"User-Agent injection: ENABLED")

    # ── 3. Run tests ───────────────────────────────────────────────
    results = {}

    if args.test in ('all', 'counts'):
        results['offer_state_counts'] = test_offer_state_counts(facade)

    if args.test in ('all', 'offers'):
        results['search_offers'] = test_search_offers(facade)

    if args.test in ('all', 'orders'):
        results['seller_orders'] = test_seller_orders(facade)

    if args.test in ('all', 'notifications'):
        results['notifications'] = test_notifications(facade, page_size=args.page_size, cursor=args.cursor)

    if args.test == 'upload':
        if not args.image:
            print("\nERROR: --image required for upload test")
            print("  Example: --test upload --image backend/output/payload_pipeline/fortnite/images/225029569/fortnite_pickaxes_normalized.png")
            sys.exit(1)
        results['upload_image'] = test_upload_image(facade, args.image)

    # ── 4. Summary ─────────────────────────────────────────────────
    print("\n\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {test_name}")

    all_passed = all(results.values())
    print(f"\n  Overall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    sys.exit(0 if all_passed else 1)


if __name__ == '__main__':
    main()
