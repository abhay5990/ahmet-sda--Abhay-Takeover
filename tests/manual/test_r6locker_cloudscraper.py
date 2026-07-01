"""Test R6Locker with cloudscraper.

Strategy:
1. cloudscraper session olustur (Cloudflare challenge'i cozmeye calisir)
2. Once profil sayfasina git (challenge varsa coz, cookie al)
3. Ayni session ile /accounts/ API'ye istek at
"""

import json
import time
import cloudscraper

TEST_UUID = "8c082447-d956-4f16-af28-7e692af4d4c3"
PROFILE_URL = f"https://r6skins.locker/profile/{TEST_UUID}"
API_URL = f"https://r6skins.locker/accounts/{TEST_UUID}"


def sep(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def test_direct_api():
    """1) Direkt API'ye istek — cloudscraper challenge'i cozebilir mi?"""
    sep("Test 1: Direct API call")

    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
    )

    print(f"  URL: {API_URL}")
    start = time.time()
    resp = scraper.get(API_URL)
    elapsed = time.time() - start

    print(f"  Status: {resp.status_code}")
    print(f"  Time: {elapsed:.2f}s")

    if resp.status_code == 200:
        try:
            data = resp.json()
            print(f"  JSON keys: {list(data.keys())[:8]}")
            print(f"  username: {data.get('username', '?')}")
            print("  RESULT: OK")
        except Exception:
            print(f"  Body: {resp.text[:200]}")
            print("  RESULT: FAIL (not JSON)")
    else:
        print(f"  Body: {resp.text[:200]}")
        print(f"  RESULT: FAIL (HTTP {resp.status_code})")

    # Show cookies
    print(f"  Cookies: {dict(scraper.cookies)}")


def test_warmup_then_api():
    """2) Once profil sayfasina git, sonra API'ye istek at."""
    sep("Test 2: Warmup (profile page) -> API call")

    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
    )

    # Step 1: Profil sayfasina git
    print(f"  Step 1: GET {PROFILE_URL}")
    start = time.time()
    resp1 = scraper.get(PROFILE_URL)
    elapsed1 = time.time() - start
    print(f"  Status: {resp1.status_code} ({elapsed1:.2f}s)")
    print(f"  Cookies after warmup: {dict(scraper.cookies)}")

    has_clearance = any('cf_clearance' in c for c in scraper.cookies.keys())
    print(f"  cf_clearance obtained: {has_clearance}")

    # Step 2: API'ye istek at
    print(f"\n  Step 2: GET {API_URL}")
    headers = {
        'accept': '*/*',
        'referer': PROFILE_URL,
    }
    start = time.time()
    resp2 = scraper.get(API_URL, headers=headers)
    elapsed2 = time.time() - start

    print(f"  Status: {resp2.status_code} ({elapsed2:.2f}s)")

    if resp2.status_code == 200:
        try:
            data = resp2.json()
            print(f"  JSON keys: {list(data.keys())[:8]}")
            print(f"  username: {data.get('username', '?')}")
            print("  RESULT: OK")
        except Exception:
            print(f"  Body: {resp2.text[:200]}")
            print("  RESULT: FAIL (not JSON)")
    else:
        print(f"  Body: {resp2.text[:200]}")
        print(f"  RESULT: FAIL (HTTP {resp2.status_code})")


def test_with_delay():
    """3) Warmup + 2sn bekleme + API (belki Cloudflare delay istiyor)."""
    sep("Test 3: Warmup + 2s delay -> API call")

    scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
        delay=5,
    )

    print(f"  Step 1: GET {PROFILE_URL}")
    start = time.time()
    resp1 = scraper.get(PROFILE_URL)
    elapsed1 = time.time() - start
    print(f"  Status: {resp1.status_code} ({elapsed1:.2f}s)")
    print(f"  Cookies: {list(scraper.cookies.keys())}")

    print("  Waiting 2s...")
    time.sleep(2)

    print(f"  Step 2: GET {API_URL}")
    headers = {'referer': PROFILE_URL}
    start = time.time()
    resp2 = scraper.get(API_URL, headers=headers)
    elapsed2 = time.time() - start

    print(f"  Status: {resp2.status_code} ({elapsed2:.2f}s)")

    if resp2.status_code == 200:
        try:
            data = resp2.json()
            print(f"  username: {data.get('username', '?')}")
            print("  RESULT: OK")
        except Exception:
            print("  RESULT: FAIL (not JSON)")
    else:
        print(f"  Body: {resp2.text[:200]}")
        print(f"  RESULT: FAIL (HTTP {resp2.status_code})")


if __name__ == "__main__":
    print("R6Locker Cloudscraper Test")
    test_direct_api()
    test_warmup_then_api()
    test_with_delay()
    sep("DONE")
