"""Test R6Locker with DrissionPage.

Strategy:
1. DrissionPage ile headless Chromium ac
2. Profil sayfasina git, Cloudflare challenge'i browser cozsun
3. cf_clearance cookie'yi al
4. Bu cookie ile requests/curl_cffi uzerinden API'ye istek at
5. Ayni cookie ile birden fazla hesap sorgula

Kullanim:
    python tests/manual/test_r6locker_drission.py
"""

import json
import time

import requests

TEST_UUIDS = [
    "8c082447-d956-4f16-af28-7e692af4d4c3",
    "d2262a5b-d6c4-4030-8059-3f3ad4c0c9e4",
]

BASE_URL = "https://r6skins.locker"


def sep(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def get_cf_clearance():
    """DrissionPage ile Cloudflare challenge'i coz, cookie dondur."""
    from DrissionPage import ChromiumPage, ChromiumOptions

    sep("Step 1: Getting cf_clearance via DrissionPage")

    co = ChromiumOptions()
    co.headless(False)
    co.set_argument('--no-sandbox')
    co.set_argument('--disable-gpu')
    co.set_argument('--disable-blink-features=AutomationControlled')

    page = ChromiumPage(co)

    profile_url = f"{BASE_URL}/profile/{TEST_UUIDS[0]}"
    print(f"  Navigating to: {profile_url}")

    start = time.time()
    page.get(profile_url)

    # Cloudflare challenge'in cozulmesini bekle
    print("  Waiting for Cloudflare challenge to resolve...")
    max_wait = 45
    for i in range(max_wait):
        title = page.title or ""
        if "moment" not in title.lower() and "dakika" not in title.lower() and "wait" not in title.lower():
            print(f"    Challenge resolved at {i+1}s")
            break
        time.sleep(1)
        if (i + 1) % 5 == 0:
            print(f"    Still waiting... ({i+1}s) title='{title}'")

    elapsed = time.time() - start
    print(f"  Page title: {page.title}")
    print(f"  Time: {elapsed:.2f}s")

    # Cookie'leri al
    cookies = page.cookies()
    cookie_dict = {}
    user_agent = page.run_js("return navigator.userAgent")

    for c in cookies:
        name = c.get('name', '')
        value = c.get('value', '')
        if name:
            cookie_dict[name] = value

    print(f"  Cookies found: {list(cookie_dict.keys())}")
    print(f"  User-Agent: {user_agent}")

    cf_clearance = cookie_dict.get('cf_clearance', '')
    connect_sid = cookie_dict.get('connect.sid', '')

    if cf_clearance:
        print(f"  cf_clearance: {cf_clearance[:40]}...")
        print("  RESULT: OK")
    else:
        print("  RESULT: FAIL - no cf_clearance cookie")

    page.quit()

    return {
        'cf_clearance': cf_clearance,
        'connect.sid': connect_sid,
        'user_agent': user_agent,
        'all_cookies': cookie_dict,
    }


def test_api_with_cookies(cookie_info):
    """Alinan cookie ile requests uzerinden API'ye istek at."""
    sep("Step 2: API calls with cf_clearance cookie")

    if not cookie_info.get('cf_clearance'):
        print("  SKIP - no cf_clearance cookie available")
        return

    session = requests.Session()

    # Cookie'leri set et
    session.cookies.set('cf_clearance', cookie_info['cf_clearance'], domain='r6skins.locker')
    if cookie_info.get('connect.sid'):
        session.cookies.set('connect.sid', cookie_info['connect.sid'], domain='r6skins.locker')

    session.headers.update({
        'accept': '*/*',
        'cache-control': 'no-cache',
        'pragma': 'no-cache',
        'user-agent': cookie_info.get('user_agent', ''),
        'sec-ch-ua-platform': '"Windows"',
    })

    # Birden fazla hesabi sorgula
    success = 0
    fail = 0

    for uuid in TEST_UUIDS:
        api_url = f"{BASE_URL}/accounts/{uuid}"
        session.headers['referer'] = f"{BASE_URL}/profile/{uuid}"

        print(f"\n  GET {api_url}")
        start = time.time()
        resp = session.get(api_url)
        elapsed = time.time() - start

        print(f"  Status: {resp.status_code} ({elapsed:.2f}s)")

        if resp.status_code == 200:
            try:
                data = resp.json()
                username = data.get('username', '?')
                level = data.get('level', '?')
                print(f"  username: {username}, level: {level}")
                print("  OK")
                success += 1
            except Exception:
                print(f"  Body: {resp.text[:150]}")
                print("  FAIL (not JSON)")
                fail += 1
        else:
            print(f"  Body: {resp.text[:150]}")
            print(f"  FAIL (HTTP {resp.status_code})")
            fail += 1

    sep(f"Results: {success} OK, {fail} FAIL out of {len(TEST_UUIDS)}")


if __name__ == "__main__":
    print("R6Locker DrissionPage Test")
    cookie_info = get_cf_clearance()
    test_api_with_cookies(cookie_info)
