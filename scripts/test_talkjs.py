"""Test TalkJS client — fetch messages for a conversation.

Usage (from project root):
    python scripts/test_talkjs.py
"""

from __future__ import annotations

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

# Add libs to path so apis_sdk is importable
sys.path.insert(0, os.path.join(PROJECT_ROOT, "libs", "apis_sdk"))

from apis_sdk.factories.talkjs_factory import TalkJsFactory  # noqa: E402

# -- Hardcoded TalkJS credentials ---------------------------------------------
APP_ID = "49mLECOW"
USER_ID = "f6c20ed5e8d75698e8aa_n"
EXTERN_ID = "auth0|60c56ad815589d0069348b4b"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlblR5cGUiOiJ1c2VyIiwic3ViIjoiYXV0aDB8NjBjNTZhZDgxNTU4OWQwMDY5MzQ4YjRiIiwiZXhwIjoxNzc3MDgxNDc5LCJpc3MiOiI0OW1MRUNPVyJ9._mYU6kBVxuQLe9-hLH4obbXNaEWC4M-1ae7Sir7Tkug"  # FILL THIS IN — boken/authToken from browser

# -- Test conversation (from the Roblox order we found earlier) ----------------
CONVERSATION_ID = ""  # TalkJS conversation ID — FILL IN bcda90d42141d33996fa
EXTERNAL_CONV_ID = "3e0fd628-30d5-498f-9169-20559c358ed0"  # same as conversation_id for Eldorado orders
# ------------------------------------------------------------------------------


def main() -> None:
    if not TOKEN:
        print("ERROR: Fill in TOKEN first!")
        return
    if not CONVERSATION_ID:
        print("ERROR: Fill in CONVERSATION_ID first!")
        return

    client = TalkJsFactory.create(
        app_id=APP_ID,
        user_id=USER_ID,
        token=TOKEN,
        extern_id=EXTERN_ID,
    )

    print(f"=== TalkJS — Fetch messages for {CONVERSATION_ID} ===\n")

    result = client.get_messages(
        conversation_id=CONVERSATION_ID,
        external_conv_id=EXTERNAL_CONV_ID or None,
    )

    print(f"OK      : {result.ok}")
    print(f"Status  : {result.status_code}")

    if result.ok:
        messages = result.data or []
        print(f"Messages: {len(messages)}\n")
        for msg in messages:
            sender = "ME" if msg.sender_id == USER_ID else msg.sender_id
            print(f"  [{sender}] {msg.text}")
    else:
        print(f"Error   : {result.error}")


if __name__ == "__main__":
    main()
