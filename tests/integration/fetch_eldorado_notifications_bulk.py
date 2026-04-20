"""
Eldorado notifications — bulk fetch (last N pages).

Fetches up to MAX_PAGES pages of unread notifications and writes all results
to output/integration/eldorado_notifications_bulk.json.

Usage (from project root):
    python tests/integration/fetch_eldorado_notifications_bulk.py
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
MAX_PAGES = 20
PAGE_SIZE = 50
OUTPUT_DIR = PROJECT_ROOT / "output" / "integration"
OUTPUT_FILE = OUTPUT_DIR / "eldorado_notifications_bulk.json"

FIRST_CURSOR = "9999-99-99 99:99:99.999999999999999-9999-9999-9999-999999999999"


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

    all_results: list[dict] = []
    cursor = FIRST_CURSOR
    page = 0

    while page < MAX_PAGES:
        page += 1
        params = {
            "cursorValue": cursor,
            "pageDirection": "Next",
            "pageSize": str(PAGE_SIZE),
            "notificationReadStatuses": "IsUnread",
        }

        result = facade.get_notifications(params=params)

        if not result.ok:
            err = result.error
            print(f"  ERROR on page {page}: [{err.category}] {err.message}")
            break

        data = result.data
        batch = [item.model_dump() for item in data.results]
        all_results.extend(batch)

        print(f"  Page {page:>2} : {len(batch):>3} items  (total so far: {len(all_results)})")

        if not data.nextPageCursor or len(batch) == 0:
            print("  No more pages.")
            break

        cursor = data.nextPageCursor

    # ── Summary by event/type ─────────────────────────────────────────────
    from collections import Counter
    type_counts: Counter = Counter()
    event_counts: Counter = Counter()
    type_event_counts: Counter = Counter()

    for item in all_results:
        n = item.get("notification", {})
        t = n.get("type", "?")
        e = n.get("event", "?")
        type_counts[t] += 1
        event_counts[e] += 1
        type_event_counts[f"{t} / {e}"] += 1

    print(f"\n{'='*50}")
    print(f"  Total notifications : {len(all_results)}")
    print(f"\n  By type:")
    for k, v in type_counts.most_common():
        print(f"    {k:<30} {v}")
    print(f"\n  By event:")
    for k, v in event_counts.most_common():
        print(f"    {k:<30} {v}")
    print(f"\n  By type / event:")
    for k, v in type_event_counts.most_common():
        print(f"    {k:<45} {v}")
    print(f"{'='*50}")

    # ── Write output ──────────────────────────────────────────────────────
    output = {
        "_meta": {
            "account": account.slug,
            "pages_fetched": page,
            "total": len(all_results),
            "type_counts": dict(type_counts),
            "event_counts": dict(event_counts),
            "type_event_counts": dict(type_event_counts),
        },
        "results": all_results,
    }
    OUTPUT_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Written : {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
