"""
Eldorado seller reviews — raw JSON dump.

Fetches negative reviews for the first active Eldorado account in DB and writes
the raw response body to output/integration/eldorado_reviews.json.

Usage (from project root):
    python tests/integration/fetch_eldorado_reviews.py
"""

import json
import os
import sys
from pathlib import Path

# ── Bootstrap Django ────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402
django.setup()

from apps.integrations.models import IntegrationAccount  # noqa: E402
from apps.integrations.providers.registry import get_or_build_client  # noqa: E402

# ── Config ───────────────────────────────────────────────────────────────────
OUTPUT_DIR = PROJECT_ROOT / "output" / "integration"
OUTPUT_FILE = OUTPUT_DIR / "eldorado_reviews.json"

REVIEWS_PATH = "/api/orders/me/reviews"

_raw_body: dict | list | None = None


def install_capture_hook(facade):
    transport = facade._exec._transport
    original_request = transport.request

    def hooked(method, url, **kwargs):
        resp = original_request(method, url, **kwargs)
        if "reviews" in url:
            global _raw_body
            try:
                _raw_body = resp.json()
            except Exception:
                _raw_body = {"_raw_text": resp.body.decode("utf-8", errors="replace")}
        return resp

    transport.request = hooked


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    account = (
        IntegrationAccount.objects
        .select_related("credential")
        .filter(provider="eldorado", is_active=True)
        .first()
    )
    if not account:
        sys.exit("ERROR: No active Eldorado account found in DB")

    print(f"Account : {account.slug}")

    facade = get_or_build_client("eldorado", account.credential)
    install_capture_hook(facade)

    # Reviews endpoint — direkt client üzerinden (facade'e henüz eklenmedi)
    auth_headers = facade._exec.get_auth_headers()
    params = {
        "cursorValue": "9999-99-99 99:99:99.999999999999999-9999-9999-9999-999999999999",
        "pageDirection": "Next",
        "pageSize": "7",
        "feedbackRating": "Negative",
    }

    from apis_sdk.core.enums import HttpMethod
    url = f"{facade._client._config.base_url}{REVIEWS_PATH}"
    resp = facade._exec._transport.request(
        HttpMethod.GET,
        url,
        headers=auth_headers,
        params=params,
        timeout=30,
        proxy_url=None,
    )

    print(f"Status  : {resp.status_code}")

    try:
        body = resp.json()
    except Exception:
        body = {"_raw_text": resp.body.decode("utf-8", errors="replace")}

    OUTPUT_FILE.write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Written : {OUTPUT_FILE}")

    if isinstance(body, dict):
        results = body.get("results", [])
        print(f"Results : {len(results)} review(s)")
        if results:
            print(f"\nİlk item anahtarları:\n  {list(results[0].keys())}")


if __name__ == "__main__":
    main()
