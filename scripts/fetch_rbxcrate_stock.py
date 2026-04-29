"""Fetch available Robux stock from RobuxCrate API.

Usage (from project root):
    python scripts/fetch_rbxcrate_stock.py
"""

from __future__ import annotations

import json
import os
import sys

# -- Bootstrap Django --------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, 'backend')

sys.path.insert(0, BACKEND_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

import django  # noqa: E402
django.setup()

from apps.integrations.models import ServiceCredential  # noqa: E402
from apps.integrations.services.robuxcrate import RobuxCrateService  # noqa: E402


def _build_client():
    cred = ServiceCredential.objects.get(slug="game-service-rbxcrate")
    return RobuxCrateService.build_client(cred)


def fetch_stock() -> None:
    client = _build_client()

    print("=== RobuxCrate GET /orders/detailed-stock ===\n")
    result = client.get_detailed_stock()

    print(f"OK      : {result.ok}")
    print(f"Status  : {result.status_code}")

    if result.ok:
        print(f"Response:\n{json.dumps(result.data, indent=2)}")
    else:
        print(f"Error   : {result.error}")


def test_order() -> None:
    """Test a gamepass order. Fill in values below before running."""
    client = _build_client()

    # -- Hardcoded test values (FILL THESE IN) --------------------------------
    ORDER_ID = "d44bb0e0-6da1-42ec-9f64-59b05ef6ea86"              # unique order id (any string, e.g. "test-001")
    ROBLOX_USERNAME = "0Julialice"       # buyer's roblox username
    ROBUX_AMOUNT = 1400           # robux amount to send
    PLACE_ID = 503565601               # gamepass id from the link
    IS_PRE_ORDER = True
    CHECK_OWNERSHIP = False
    # -------------------------------------------------------------------------
    #503565601/my-house#!/store

    if not ORDER_ID or not ROBLOX_USERNAME or not ROBUX_AMOUNT or not PLACE_ID:
        print("ERROR: Fill in ORDER_ID, ROBLOX_USERNAME, ROBUX_AMOUNT, PLACE_ID first!")
        return

    print("=== RobuxCrate POST /orders/gamepass ===\n")
    print(f"Order ID : {ORDER_ID}")
    print(f"Username : {ROBLOX_USERNAME}")
    print(f"Amount   : {ROBUX_AMOUNT}")
    print(f"Place ID : {PLACE_ID}")
    print(f"PreOrder : {IS_PRE_ORDER}")
    print()

    result = client.create_gamepass_order(
        order_id=ORDER_ID,
        roblox_username=ROBLOX_USERNAME,
        robux_amount=ROBUX_AMOUNT,
        place_id=PLACE_ID,
        is_pre_order=IS_PRE_ORDER,
        check_ownership=CHECK_OWNERSHIP,
    )

    print(f"OK      : {result.ok}")
    print(f"Status  : {result.status_code}")

    if result.ok:
        print(f"Response:\n{json.dumps(result.data, indent=2)}")
    else:
        print(f"Error   : {result.error}")


# -- Run ---------------------------------------------------------------------
if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "stock"

    if action == "stock":
        fetch_stock()
    elif action == "order":
        test_order()
    else:
        print(f"Usage: python {sys.argv[0]} [stock|order]")
else:
    fetch_stock()
