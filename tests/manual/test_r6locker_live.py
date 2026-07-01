"""Live smoke test — R6Locker API via CurlCffiTransport.

Bu test GERÇEK API'ye istek atar. Mock yok, proxy yok.
Amacı: CurlCffi + R6Locker'ın Cloudflare'ı geçip geçemediğini doğrulamak.

Kullanım:
    cd backend && python ../tests/manual/test_r6locker_live.py

Bilinen public profil UUID'si gerekir (aşağıdaki TEST_UUID).
"""

import os
import sys
import time

# Path setup
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'libs', 'apis_sdk'))

from apis_sdk.clients.trackers.r6locker.client import R6LockerClient
from apis_sdk.clients.trackers.r6locker.config import R6LockerConfig
from apis_sdk.factories.r6locker_factory import R6LockerFactory
from apis_sdk.infrastructure.http.curl_cffi_transport import CurlCffiTransport

# Bilinen public bir R6Locker profili — değiştirmek istersen buraya kendi UUID'ni yaz
TEST_UUID = "d2262a5b-d6c4-4030-8059-3f3ad4c0c9e4"


def sep(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def test_transport_basic():
    """1) CurlCffiTransport raw GET — Cloudflare'ı geçiyor mu?"""
    sep("Test 1: Raw CurlCffi transport GET")

    transport = CurlCffiTransport()
    from apis_sdk.core.enums import HttpMethod

    url = f"https://r6skins.locker/accounts/{TEST_UUID}"
    headers = {
        "accept": "*/*",
        "cache-control": "no-cache",
        "pragma": "no-cache",
        "referer": f"https://r6skins.locker/profile/{TEST_UUID}",
    }

    print(f"  URL: {url}")
    print(f"  Headers: {headers}")

    start = time.time()
    try:
        resp = transport.request(
            HttpMethod.GET,
            url,
            headers=headers,
            timeout=30.0,
        )
        elapsed = time.time() - start
        print(f"  Status: {resp.status_code}")
        print(f"  Time: {elapsed:.2f}s")
        print(f"  Body length: {len(resp.body)} bytes")

        if resp.is_success:
            import json
            try:
                data = json.loads(resp.body)
                print(f"  JSON keys: {list(data.keys()) if isinstance(data, dict) else type(data).__name__}")
                if isinstance(data, dict) and data.get("username"):
                    print(f"  Username: {data['username']}")
                print("  RESULT: OK")
            except json.JSONDecodeError:
                print(f"  Body preview: {resp.body[:200]}")
                print("  RESULT: FAIL — response is not JSON (possibly Cloudflare challenge page)")
        else:
            print(f"  Body preview: {resp.body[:300]}")
            print(f"  RESULT: FAIL — HTTP {resp.status_code}")
    except Exception as exc:
        elapsed = time.time() - start
        print(f"  RESULT: EXCEPTION after {elapsed:.2f}s")
        print(f"  {type(exc).__name__}: {exc}")

    transport.close()


def test_client_direct():
    """2) R6LockerClient.get_account_data — ApiResult dönüyor mu?"""
    sep("Test 2: R6LockerClient.get_account_data")

    transport = CurlCffiTransport()
    config = R6LockerConfig()
    client = R6LockerClient(config=config, transport=transport)

    print(f"  account_id: {TEST_UUID}")

    start = time.time()
    result = client.get_account_data(TEST_UUID)
    elapsed = time.time() - start

    print(f"  Time: {elapsed:.2f}s")
    print(f"  result.ok: {result.ok}")

    if result.ok:
        data = result.data
        print(f"  Data type: {type(data).__name__}")
        if isinstance(data, dict):
            print(f"  Keys: {list(data.keys())[:10]}")
            print(f"  username: {data.get('username', '?')}")
            print(f"  level: {data.get('level', '?')}")
        print("  RESULT: OK")
    else:
        print(f"  Error: {result.error.message if result.error else 'unknown'}")
        print("  RESULT: FAIL")

    transport.close()


def test_facade_via_factory():
    """3) Factory → Facade — production'daki aynı akış."""
    sep("Test 3: R6LockerFactory.create -> facade.get_account_data")

    transport = CurlCffiTransport()
    facade = R6LockerFactory.create(transport=transport)

    print(f"  account_id: {TEST_UUID}")

    start = time.time()
    result = facade.get_account_data(TEST_UUID)
    elapsed = time.time() - start

    print(f"  Time: {elapsed:.2f}s")
    print(f"  result.ok: {result.ok}")

    if result.ok:
        data = result.data
        if isinstance(data, dict):
            print(f"  Keys: {list(data.keys())[:10]}")
            print(f"  username: {data.get('username', '?')}")
        print("  RESULT: OK")
    else:
        print(f"  Error: {result.error.message if result.error else 'unknown'}")
        print("  RESULT: FAIL")

    transport.close()


def test_invalid_uuid():
    """4) Geçersiz UUID — 404 mü dönüyor yoksa Cloudflare mı engelliyor?"""
    sep("Test 4: Invalid UUID (expect 404 or not_found)")

    transport = CurlCffiTransport()
    facade = R6LockerFactory.create(transport=transport)

    fake_uuid = "00000000-0000-0000-0000-000000000000"
    print(f"  account_id: {fake_uuid}")

    start = time.time()
    result = facade.get_account_data(fake_uuid)
    elapsed = time.time() - start

    print(f"  Time: {elapsed:.2f}s")
    print(f"  result.ok: {result.ok}")

    if not result.ok:
        err = result.error
        print(f"  Error category: {err.category if err else '?'}")
        print(f"  Error message: {err.message if err else '?'}")
        print(f"  Status code: {result.status_code}")
        print("  RESULT: OK (expected failure)")
    else:
        print(f"  Unexpected success with data: {result.data}")
        print("  RESULT: UNEXPECTED")

    transport.close()


if __name__ == "__main__":
    print("R6Locker Live Smoke Test")
    print(f"Test UUID: {TEST_UUID}")

    test_transport_basic()
    test_client_direct()
    test_facade_via_factory()
    test_invalid_uuid()

    sep("DONE")
