"""E2E manuel test — R6 tracker'ı GERÇEK posting giriş noktasından sürer.

orchestrator'ın çağırdığı yolun aynısı:
    fetch_tracker_data('rainbow-six-siege', raw_data)
  -> _fetch_r6 -> R6LockerFacade -> CfCookieProvider (nodriver solve, DB proxy)
  -> curl_cffi (aynı sticky IP) -> /accounts/<uuid> -> tracker dict

Birden çok hesap verir: tek solve + reuse (facade cache) gözlemlenir.
GERÇEK tarayıcı açar (Xvfb :99) ve gerçek ağ + residential proxy kullanır.

ÖNEMLİ: Aktif kod `if __name__ == "__main__"` altında — provider solve'u
subprocess ('spawn') açar; guard olmadan sonsuz spawn olur.

Kullanım (xvfb.service :99 ayaktayken):
    DISPLAY=:99 venv/bin/python tests/manual/test_r6locker_e2e.py
"""

from __future__ import annotations

import os
import sys
import time


def main() -> None:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    sys.path.insert(0, os.path.join(root, "backend"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    os.environ.setdefault("DISPLAY", ":99")
    import django
    django.setup()

    from apps.posting.services.shared.tracker_fetcher import fetch_tracker_data

    accounts = [
        "8c082447-d956-4f16-af28-7e692af4d4c3",  # ilk çağrı -> tek solve tetikler
        "2a59b57f-8fa0-4bb3-b0c0-bf936b7613d7",  # bundan sonrası cache reuse
        "d75badeb-4734-42fc-816f-f2873b1fed51",
    ]

    print(f"E2E: {len(accounts)} hesap, posting giriş noktası fetch_tracker_data\n")
    ok = 0
    for i, uuid in enumerate(accounts, 1):
        raw_data = {"uplay_id": uuid}
        t0 = time.monotonic()
        data = fetch_tracker_data("rainbow-six-siege", raw_data)
        dt = time.monotonic() - t0
        if data:
            ok += 1
            uname = data.get("username", "?")
            lvl = data.get("level", "?")
            print(f"  {i}  {uuid[:8]}  {dt:5.1f}s  OK {uname} (level {lvl})")
        else:
            print(f"  {i}  {uuid[:8]}  {dt:5.1f}s  FAIL None (tracker fetch failed)")

    print(f"\nSONUC: {ok}/{len(accounts)} hesap tracker verisi dondu")
    print("(1. hesap solve suresini icerir; sonrakiler hizli olmali = cache reuse)")
    sys.exit(0 if ok == len(accounts) else 1)


if __name__ == "__main__":
    main()
