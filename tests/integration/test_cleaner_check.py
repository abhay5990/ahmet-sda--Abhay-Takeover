"""LZT cleaner item check — tek bir item'a istek atip sonucu gosterir.

Kullanim (proje root'undan):
    python tests/integration/test_cleaner_check.py
    python tests/integration/test_cleaner_check.py lzt_main 12345678 87654321
    python tests/integration/test_cleaner_check.py lzt_main 12345678 --raw
"""

import json
import os
import sys
from decimal import Decimal

# ---------------------------------------------------------------------------
# Ayarlar — buralari degistir
# ---------------------------------------------------------------------------

SOURCE_ACCOUNT_SLUG = "lzt-gandalfrivendell"
ITEM_IDS = ["220112698"]           # test etmek istedigin item ID'leri
SHOW_RAW = False                  # True yaparsan full raw_data basilir

# ---------------------------------------------------------------------------
# Django bootstrap
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")

sys.path.insert(0, BACKEND_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django  # noqa: E402
django.setup()

# ---------------------------------------------------------------------------
# Imports (Django hazir olduktan sonra)
# ---------------------------------------------------------------------------

from apps.integrations.models import IntegrationAccount          # noqa: E402
from apps.integrations.providers import registry                 # noqa: E402
from apps.integrations.proxy_pool import get_group_name          # noqa: E402
from apps.posting.services.dropship.backoff import classify_api_error  # noqa: E402
from apps.posting.services.dropship.source_provider import get_source_provider  # noqa: E402
import apps.posting.services.dropship.sources                    # noqa: E402, F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _header(text: str) -> str:
    return f"\n{'=' * 60}\n{text}\n{'=' * 60}"


def _sub(text: str) -> str:
    return f"\n--- {text} ---"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    slug = SOURCE_ACCOUNT_SLUG
    item_ids = list(ITEM_IDS)
    show_raw = SHOW_RAW

    # CLI override
    args = sys.argv[1:]
    if args and not args[0].startswith("--"):
        slug = args.pop(0)
    if "--raw" in args:
        show_raw = True
        args.remove("--raw")
    if args:
        item_ids = args

    # Resolve source account
    try:
        account = IntegrationAccount.objects.select_related("credential").get(slug=slug)
    except IntegrationAccount.DoesNotExist:
        available = list(IntegrationAccount.objects.values_list("slug", flat=True))
        print(f"[ERROR] Account '{slug}' not found. Available: {', '.join(available)}")
        return

    print(f"Source account : {account.slug} (provider={account.provider})")

    # Build provider + proxy
    source_provider = get_source_provider(account.provider, account.credential)
    proxy_group = get_group_name(account)
    print(f"Proxy group    : {proxy_group or '(none)'}")

    # Raw facade
    facade = registry.get_or_build_client(account.provider, account.credential)

    for item_id in item_ids:
        print(_header(f"Item ID: {item_id}"))

        # ---- 1. Raw API response ----
        print(_sub("1. Raw API Response"))
        raw_result = facade.get_item(item_id, proxy_group=proxy_group)

        print(f"  ok       : {raw_result.ok}")
        print(f"  status   : {raw_result.status_code}")

        if raw_result.error:
            print(f"  error    : {raw_result.error}")
            print(f"  err_cat  : {getattr(raw_result.error, 'category', 'N/A')}")
            print(f"  err_type : {getattr(raw_result.error, 'type', 'N/A')}")

        if raw_result.data:
            data = raw_result.data
            item_data = data.get("item", data)

            # ---- 2. Key fields ----
            print(_sub("2. Key Fields"))
            fields = [
                "item_id", "item_state", "status", "price",
                "title", "title_en", "category_id",
                "is_sold", "is_sticky", "candle_count",
            ]
            for f in fields:
                val = item_data.get(f, "(missing)")
                print(f"  {f:20s}: {val}")

            # Full raw
            if show_raw:
                print(_sub("2b. Full raw_data"))
                print(json.dumps(item_data, indent=2, default=str)[:3000])

        # ---- 3. Cleaner interpretation ----
        print(_sub("3. Cleaner Interpretation (ItemCheckResult)"))
        check = source_provider.check_item(item_id, proxy_group=proxy_group)

        print(f"  exists        : {check.exists}")
        print(f"  status        : {check.status}")
        print(f"  current_price : {check.current_price}")

        # ---- 4. Cleaner decision simulation ----
        print(_sub("4. Cleaner Decision (simulated)"))

        if check.status == "api_error":
            api_result = check.raw_data.get("api_result")
            if api_result:
                error_type = classify_api_error(api_result)
                print(f"  -> API ERROR: {error_type}")
                actions = {
                    "rate_limit": "backoff (rate limited)",
                    "server": "backoff (server error)",
                    "not_found": "_handle_item_gone(reason='deleted')",
                    "auth": "_handle_item_gone(reason='deleted')",
                    "maintenance": f"wait {int(120)}s then retry cycle",
                }
                print(f"     Action: {actions.get(error_type, f'log warning, skip ({error_type})')}")
            else:
                print("  -> API ERROR (no result)")

        elif not check.exists:
            reason = check.status or "deleted"
            new_status = "SOLD" if reason in ("sold", "closed") else "DELETED"
            print(f"  -> ITEM GONE: reason='{reason}'")
            print(f"     Action: _handle_item_gone -> status={new_status}")

        elif check.current_price and check.current_price > 0:
            print(f"  -> ITEM EXISTS: price={check.current_price}")
            print(f"     3% tolerance ile karsilastirilir (stored dp.price'a gore)")
            print(f"     Ornek: dp.price=100 vs current={check.current_price}")
            pct = abs(check.current_price - Decimal("100")) / Decimal("100") * 100
            print(f"     -> %{pct:.1f} degisim {'-> SILER (>3%)' if pct > 3 else '-> no action (<=3%)'}")

        else:
            print("  -> ITEM EXISTS: price yok")
            print("     Action: update last_checked_at")

        print()


if __name__ == "__main__":
    main()
