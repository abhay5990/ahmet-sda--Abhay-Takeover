"""Unit tests for the shared tracker data fetcher.

Tests cover:
- _extract_r6_account_id: all ID extraction paths
- fetch_tracker_data: R6 flow with injected (mocked) R6Locker facade
- fetch_tracker_data: unsupported game slug → None, no API call
- fetch_tracker_data: missing account ID → None, no API call
- fetch_tracker_data: facade API error → None (graceful degradation)

Usage:
    cd backend && python -m pytest ../tests/unit/test_tracker_fetcher.py -v
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

# Add backend to path so `apps.*` imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))
# Add libs to path so `payload_pipeline.*` and `apis_sdk.*` imports resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'libs', 'payload_pipeline'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'libs', 'apis_sdk'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')

import django
django.setup()

from apps.posting.services.shared.tracker_fetcher import (
    _extract_r6_account_id,
    fetch_tracker_data,
)


# ---------------------------------------------------------------------------
# _extract_r6_account_id
# ---------------------------------------------------------------------------

class TestExtractR6AccountId:
    def test_flat_uplay_id(self):
        item = {"uplay_id": "abc-uuid-123", "tracker_link": None}
        assert _extract_r6_account_id(item) == "abc-uuid-123"

    def test_uplay_id_takes_priority_over_tracker_link(self):
        item = {"uplay_id": "uuid-primary", "tracker_link": "r6skins.locker/profile/uuid-secondary"}
        assert _extract_r6_account_id(item) == "uuid-primary"

    def test_tracker_link_fallback_when_no_uplay_id(self):
        item = {"uplay_id": None, "tracker_link": "r6skins.locker/profile/uuid-from-link"}
        assert _extract_r6_account_id(item) == "uuid-from-link"

    def test_tracker_link_strips_trailing_slash(self):
        item = {"uplay_id": None, "tracker_link": "r6skins.locker/profile/uuid-xyz/"}
        assert _extract_r6_account_id(item) == "uuid-xyz"

    def test_masked_tracker_link(self):
        item = {"uplay_id": None, "tracker_link": "r6skins.locker/masked/masked-001"}
        assert _extract_r6_account_id(item) == "masked-001"

    def test_returns_empty_when_both_missing(self):
        assert _extract_r6_account_id({"uplay_id": None, "tracker_link": None}) == ""
        assert _extract_r6_account_id({}) == ""

    def test_returns_empty_when_uplay_id_empty_string(self):
        assert _extract_r6_account_id({"uplay_id": "", "tracker_link": ""}) == ""

    def test_description_plain_fallback(self):
        """Real dropship data format: no uplay_id/tracker_link, URL in descriptionPlain."""
        item = {
            "descriptionPlain": "https://r6skins.locker/profile/d2262a5b-d6c4-4030-8059-3f3ad4c0c9e4",
        }
        assert _extract_r6_account_id(item) == "d2262a5b-d6c4-4030-8059-3f3ad4c0c9e4"

    def test_description_en_plain_fallback(self):
        item = {
            "descriptionEnPlain": "https://r6skins.locker/profile/aabb1122-0000-0000-0000-000000000099",
        }
        assert _extract_r6_account_id(item) == "aabb1122-0000-0000-0000-000000000099"

    def test_description_plain_masked_link(self):
        item = {"descriptionPlain": "https://r6skins.locker/masked/aabbccdd-0011-2233-4455-66778899aabb"}
        assert _extract_r6_account_id(item) == "aabbccdd-0011-2233-4455-66778899aabb"

    def test_uplay_id_takes_priority_over_description_plain(self):
        item = {
            "uplay_id": "direct-uuid",
            "descriptionPlain": "https://r6skins.locker/profile/description-uuid",
        }
        assert _extract_r6_account_id(item) == "direct-uuid"

    def test_nested_item_wrapper(self):
        """LZT single-item responses wrap data under 'item' key."""
        nested = {"item": {"uplay_id": "nested-uuid", "tracker_link": None}}
        assert _extract_r6_account_id(nested) == "nested-uuid"

    def test_nested_item_wrapper_tracker_link_fallback(self):
        nested = {"item": {"uplay_id": None, "tracker_link": "r6skins.locker/profile/nested-link-id"}}
        assert _extract_r6_account_id(nested) == "nested-link-id"


# ---------------------------------------------------------------------------
# fetch_tracker_data — unsupported game
# ---------------------------------------------------------------------------

class TestFetchTrackerDataUnsupportedGame:
    def test_unsupported_game_returns_none_without_api_call(self):
        mock_facade = MagicMock()
        result = fetch_tracker_data(
            "fortnite",
            {"uplay_id": "some-id"},
            _r6_facade=mock_facade,
        )
        assert result is None
        mock_facade.get_account_data.assert_not_called()

    def test_empty_game_slug_returns_none(self):
        result = fetch_tracker_data("", {"uplay_id": "some-id"})
        assert result is None


# ---------------------------------------------------------------------------
# fetch_tracker_data — R6 with injected facade
# ---------------------------------------------------------------------------

def _make_r6_item(uplay_id="test-uuid-001", tracker_link=None):
    return {"uplay_id": uplay_id, "tracker_link": tracker_link}


def _make_ok_facade(data: dict) -> MagicMock:
    """Facade mock that returns a successful ApiResult-like object."""
    result = MagicMock()
    result.ok = True
    result.data = data
    facade = MagicMock()
    facade.get_account_data.return_value = result
    return facade


def _make_error_facade(message="not found") -> MagicMock:
    """Facade mock that returns a failed ApiResult-like object."""
    error = MagicMock()
    error.message = message
    result = MagicMock()
    result.ok = False
    result.error = error
    facade = MagicMock()
    facade.get_account_data.return_value = result
    return facade


class TestFetchTrackerDataR6:
    def test_success_returns_tracker_data(self):
        tracker_payload = {"userId": "test-uuid-001", "username": "Player1", "level": 200}
        facade = _make_ok_facade(tracker_payload)

        result = fetch_tracker_data(
            "rainbow-six-siege",
            _make_r6_item(uplay_id="test-uuid-001"),
            _r6_facade=facade,
        )

        assert result == tracker_payload
        facade.get_account_data.assert_called_once_with("test-uuid-001", proxy_group=None)

    def test_success_with_proxy_group_passed_through(self):
        facade = _make_ok_facade({"userId": "uuid-x"})

        fetch_tracker_data(
            "rainbow-six-siege",
            _make_r6_item(uplay_id="uuid-x"),
            proxy_group="residential",
            _r6_facade=facade,
        )

        facade.get_account_data.assert_called_once_with("uuid-x", proxy_group="residential")

    def test_success_uses_tracker_link_when_no_uplay_id(self):
        facade = _make_ok_facade({"userId": "link-uuid"})

        result = fetch_tracker_data(
            "rainbow-six-siege",
            _make_r6_item(uplay_id=None, tracker_link="r6skins.locker/profile/link-uuid"),
            _r6_facade=facade,
        )

        assert result is not None
        facade.get_account_data.assert_called_once_with("link-uuid", proxy_group=None)

    def test_facade_error_returns_none(self):
        facade = _make_error_facade("Account not found")

        result = fetch_tracker_data(
            "rainbow-six-siege",
            _make_r6_item(),
            _r6_facade=facade,
        )

        assert result is None

    def test_facade_raises_exception_returns_none(self):
        facade = MagicMock()
        facade.get_account_data.side_effect = ConnectionError("timeout")

        result = fetch_tracker_data(
            "rainbow-six-siege",
            _make_r6_item(),
            _r6_facade=facade,
        )

        assert result is None

    def test_missing_uplay_id_and_tracker_link_skips_api_call(self):
        """Bug case: listing item has no uplay_id → facade must NOT be called."""
        facade = MagicMock()

        result = fetch_tracker_data(
            "rainbow-six-siege",
            {"uplay_id": None, "tracker_link": None},
            _r6_facade=facade,
        )

        assert result is None
        facade.get_account_data.assert_not_called()

    def test_empty_item_skips_api_call(self):
        """Empty raw_data dict → facade must NOT be called."""
        facade = MagicMock()

        result = fetch_tracker_data(
            "rainbow-six-siege",
            {},
            _r6_facade=facade,
        )

        assert result is None
        facade.get_account_data.assert_not_called()

    def test_real_dropship_item_extracts_uuid_from_description_plain(self):
        """Real LZT dropship format: no uplay_id field, UUID in descriptionPlain."""
        real_item = {
            "item_id": 228266257,
            "descriptionPlain": "https://r6skins.locker/profile/d2262a5b-d6c4-4030-8059-3f3ad4c0c9e4",
            "descriptionEnPlain": "https://r6skins.locker/profile/d2262a5b-d6c4-4030-8059-3f3ad4c0c9e4",
            "uplay_r6_level": 52,
            "uplay_r6_rank": 0,
        }
        facade = _make_ok_facade({"userId": "d2262a5b-d6c4-4030-8059-3f3ad4c0c9e4"})

        result = fetch_tracker_data("rainbow-six-siege", real_item, _r6_facade=facade)

        assert result is not None
        facade.get_account_data.assert_called_once_with(
            "d2262a5b-d6c4-4030-8059-3f3ad4c0c9e4", proxy_group=None
        )
