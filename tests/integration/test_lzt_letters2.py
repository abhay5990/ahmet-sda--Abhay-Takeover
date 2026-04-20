"""
Minimal test script: combos.txt'den email:password çiftlerini oku,
DB'den ilk aktif LZT credential'ı al, /letters2 endpoint'ine istek at,
ham sonucu yazdır.

Kullanım:
    cd backend
    python manage.py shell -c "exec(open('../tests/integration/test_lzt_letters2.py').read())"

Veya doğrudan:
    DJANGO_SETTINGS_MODULE=config.settings.local python tests/integration/test_lzt_letters2.py
"""

import os
import sys
import json

# Django setup — paths relative to this script's location (scripts/)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "../.."))

backend_dir = os.path.join(ROOT_DIR, "backend")
libs_dir = os.path.join(ROOT_DIR, "libs", "apis_sdk")

for d in (backend_dir, libs_dir):
    if d not in sys.path:
        sys.path.insert(0, d)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

import django
django.setup()

from apps.integrations.models import IntegrationAccount, IntegrationCredential, Provider

from apis_sdk.clients.marketplaces.lzt.client import LztClient
from apis_sdk.clients.marketplaces.lzt.config import LztConfig
from apis_sdk.infrastructure.http.requests_transport import RequestsTransport


def get_lzt_token() -> str:
    """DB'den ilk aktif LZT hesabının token'ını al."""
    cred = IntegrationCredential.objects.filter(
        account__provider=Provider.LZT,
        account__is_active=True,
        is_active=True,
    ).select_related("account").first()

    if not cred:
        raise RuntimeError("Aktif LZT credential bulunamadı!")

    token = (
        cred.credentials.get("access_token")
        or cred.credentials.get("api_key")
        or cred.credentials.get("token")
        or ""
    )
    if not token:
        raise RuntimeError(f"LZT credential ({cred.account.name}) içinde token yok! Keys: {list(cred.credentials.keys())}")

    print(f"[+] LZT hesabı: {cred.account.name} (id={cred.account.id})")
    return token


def read_combos(path: str) -> list[str]:
    """combos.txt'den satırları oku."""
    with open(path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip() and ":" in line]
    print(f"[+] {len(lines)} combo okundu: {path}")
    return lines


def main():
    combos_path = os.path.join(ROOT_DIR, "backend", "tmp", "combos.txt")

    if not os.path.exists(combos_path):
        print(f"[!] combos.txt bulunamadı: {combos_path}")
        return

    token = get_lzt_token()
    combos = read_combos(combos_path)

    # Direkt client kullan — facade/retry katmanını bypass et, ham sonucu görelim
    config = LztConfig()
    transport = RequestsTransport(default_timeout=30.0)
    client = LztClient(config=config, transport=transport)

    auth_headers = {"Authorization": f"Bearer {token}"}
    output_dir = os.path.join(ROOT_DIR, "backend", "tmp", "lzt")
    all_results = []

    for i, combo in enumerate(combos):
        email = combo.split(":")[0]
        print(f"\n{'='*60}")
        print(f"[>] Test: {email}")
        print(f"{'='*60}")

        # Rate limit: istekler arası 8s bekle (LZT /letters2 limiti)
        if i > 0:
            print(f"  [~] 8s bekleniyor (rate limit)...")
            import time
            time.sleep(8)

        result = client.get_email_letters(
            email_password=combo,
            limit=10,
            auth_headers=auth_headers,
        )

        print(f"  ok      : {result.ok}")
        print(f"  status  : {result.status_code}")

        # Ham sonucu kaydet (ok veya hata fark etmez)
        raw_result = {
            "email": email,
            "ok": result.ok,
            "status_code": result.status_code,
        }

        if result.ok:
            data = result.data
            raw_result["data"] = data
            letters = data.get("letters", [])
            print(f"  letters : {len(letters)} adet")
            print(f"  email   : {data.get('email', 'N/A')}")
        else:
            error = result.error
            raw_result["error"] = {
                "category": error.category.value if error else None,
                "message": error.message if error else None,
                "details": error.details if error else None,
                "is_retryable": error.is_retryable if error else None,
                "retry_after": error.retry_after if error else None,
            }
            print(f"  error   : {error.category.value if error else 'N/A'}")
            print(f"  message : {error.message if error else 'N/A'}")

        all_results.append(raw_result)

    # Tüm sonuçları dosyaya yaz
    out_path = os.path.join(output_dir, "test_email_result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n[+] Ham sonuçlar yazıldı: {out_path}")

    transport.close()
    print(f"\n{'='*60}")
    print("[+] Bitti.")


if __name__ == "__main__":
    main()
