"""
Eldorado notifications endpoint — raw JSON dump.

Fetches notifications for the first active Eldorado account in DB and writes
the raw response body to output/integration/eldorado_notifications.json.

Usage (from project root):
    python tests/integration/fetch_eldorado_notifications.py
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

# ── Output path ─────────────────────────────────────────────────────────────
OUTPUT_DIR = PROJECT_ROOT / "output" / "integration"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE = OUTPUT_DIR / "eldorado_notifications.json"

# ── Capture raw response before Pydantic parsing ────────────────────────────
_raw_body: dict | list | None = None


def install_capture_hook(facade):
    transport = facade._exec._transport
    original_request = transport.request

    def hooked(method, url, **kwargs):
        resp = original_request(method, url, **kwargs)
        if "notifications" in url:
            global _raw_body
            try:
                _raw_body = resp.json()
            except Exception:
                _raw_body = {"_raw_text": resp.body.decode("utf-8", errors="replace")}
        return resp

    transport.request = hooked


# ── Main ────────────────────────────────────────────────────────────────────
def main():
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

    params = {
        "cursorValue": "9999-99-99 99:99:99.999999999999999-9999-9999-9999-999999999999",
        "pageDirection": "Next",
        "pageSize": "50",
        "notificationReadStatuses": "IsUnread",
    }
    result = facade.get_notifications(params=params)

    if not result.ok:
        err = result.error
        sys.exit(f"ERROR [{err.category}] {err.message}")

    raw = _raw_body or result.data.model_dump()
    OUTPUT_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Written : {OUTPUT_FILE}")
    print(f"Results : {len(result.data.results)} notification(s)")
    print(f"nextPageCursor: {result.data.nextPageCursor!r}")


if __name__ == "__main__":
    main()
