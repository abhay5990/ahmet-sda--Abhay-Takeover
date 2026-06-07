"""Fetch a fresh LZT order and save as test fixture.

Usage:
    python -m scripts.fetch_lzt_fixture --game val <login>
    python -m scripts.fetch_lzt_fixture --game cr <login>
    python -m scripts.fetch_lzt_fixture --game fn <login>

Supported game keys match fixture filenames: val, fn, r6, bs, coc, cr,
gi, gtav, lol, roblox, steam, ubisoft_connect, cs2.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "libs", "apis_sdk"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "libs", "payload_pipeline"))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

import django
django.setup()

from apps.integrations.models import IntegrationCredential
from apis_sdk.factories.lzt_factory import LztFactory
from apis_sdk.infrastructure.http.requests_transport import RequestsTransport

VALID_GAMES = [
    "val", "fn", "r6", "bs", "coc", "cr", "gi",
    "gtav", "lol", "roblox", "steam", "ubisoft_connect", "cs2",
]

FIXTURES_DIR = os.path.join(
    PROJECT_ROOT, "libs", "payload_pipeline", "tests", "fixtures",
)


def _get_lzt_facade():
    cred = IntegrationCredential.objects.filter(
        account__provider="lzt",
    ).select_related("account").first()

    if not cred:
        print("ERROR: No LZT IntegrationCredential found in DB")
        sys.exit(1)

    token = cred.credentials.get("api_key", "")
    if not token:
        print("ERROR: No api_key in credential")
        sys.exit(1)

    print(f"Using account: {cred.account.name} (id={cred.account.id})")
    transport = RequestsTransport()
    return LztFactory.create(token=token, transport=transport)


def fetch_order(login: str) -> dict | None:
    facade = _get_lzt_facade()
    result = facade.get_user_orders(params={"login": login})

    if not result.ok:
        print(f"API Error: {result.error}")
        return None

    items = result.data.items if result.data else []
    print(f"Found {len(items)} items for login '{login}'")
    return items[0] if items else None


def save_fixture(game: str, data: dict) -> str:
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    filename = f"lzt_{game}.json"
    path = os.path.join(FIXTURES_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def main():
    parser = argparse.ArgumentParser(description="Fetch LZT fixture data")
    parser.add_argument(
        "--game", "-g",
        required=True,
        choices=VALID_GAMES,
        help="Game key (e.g. val, cr, fn)",
    )
    parser.add_argument("login", help="Account login/email to search for")
    args = parser.parse_args()

    item = fetch_order(args.login)
    if not item:
        print("No item found.")
        sys.exit(1)

    path = save_fixture(args.game, item)
    print(f"\nSaved to: {path}")


if __name__ == "__main__":
    main()
