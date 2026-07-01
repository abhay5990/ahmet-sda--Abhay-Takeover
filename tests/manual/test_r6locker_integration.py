"""Integration test: R6Locker full stack with CfCookieProvider.

Tests the complete production flow:
  CfCookieProvider -> R6LockerFactory -> Facade -> Client -> API

Usage:
    python tests/manual/test_r6locker_integration.py
"""

import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'libs', 'apis_sdk'))

from apis_sdk.factories.r6locker_factory import R6LockerFactory
from apis_sdk.infrastructure.auth.cf_cookie_provider import CfCookieProvider
from apis_sdk.infrastructure.http.curl_cffi_transport import CurlCffiTransport

TEST_UUIDS = [
    "8c082447-d956-4f16-af28-7e692af4d4c3",
    "d2262a5b-d6c4-4030-8059-3f3ad4c0c9e4",
]
INVALID_UUID = "00000000-0000-0000-0000-000000000000"


def sep(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main():
    print("R6Locker Integration Test (CfCookieProvider + Facade)")

    # 1. Build the full stack
    sep("Building facade with CfCookieProvider")
    transport = CurlCffiTransport()
    cf_provider = CfCookieProvider(
        "https://r6skins.locker",
        warmup_path="/",
    )
    facade = R6LockerFactory.create(
        transport=transport,
        cf_cookie_provider=cf_provider,
    )
    print("  Stack ready.")

    # 2. Query multiple accounts (cookie should be obtained once, reused)
    sep(f"Querying {len(TEST_UUIDS)} accounts")
    success = 0
    fail = 0

    for uuid_val in TEST_UUIDS:
        print(f"\n  Account: {uuid_val}")
        start = time.time()
        result = facade.get_account_data(uuid_val)
        elapsed = time.time() - start

        print(f"  Time: {elapsed:.2f}s | ok: {result.ok}")

        if result.ok and isinstance(result.data, dict):
            print(f"  username: {result.data.get('username', '?')}")
            print(f"  level: {result.data.get('level', '?')}")
            success += 1
        else:
            err = result.error
            print(f"  Error: {err.message if err else 'unknown'}")
            fail += 1

    # 3. Test invalid UUID
    sep("Invalid UUID test")
    result = facade.get_account_data(INVALID_UUID)
    print(f"  ok: {result.ok} (expected: False)")
    if not result.ok:
        print(f"  Error: {result.error.message if result.error else '?'}")
        print("  OK (expected failure)")

    # 4. Test cookie reuse (should NOT open browser again)
    sep("Cookie reuse test (should be instant)")
    cookies = cf_provider.get_cookies()
    if cookies:
        print(f"  Cached: yes, expired: {cookies.is_expired}")
        print(f"  Cookie age: {time.time() - cookies.obtained_at:.0f}s")
    else:
        print("  No cached cookies!")

    sep(f"RESULTS: {success}/{len(TEST_UUIDS)} OK, {fail} failed")
    transport.close()


if __name__ == "__main__":
    main()
