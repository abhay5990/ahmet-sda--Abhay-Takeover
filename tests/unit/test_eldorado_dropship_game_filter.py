"""Unit tests for Eldorado dropship game/category filtering.

Bug: seller-UUID fetches must omit gameId (API returns 0 with both), so without
a client-side filter multi-game sellers' non-SAB offers were dropshipped as SAB.

Usage:
    cd backend && python -m pytest ../tests/unit/test_eldorado_dropship_game_filter.py -v
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'libs', 'payload_pipeline'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'libs', 'apis_sdk'))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')

import django
django.setup()

from apps.posting.services.dropship.sources.eldorado import (
    SAB_GAME_ID,
    EldoradoSourceProvider,
    _SELLER_UUID_CACHE,
    _coerce_game_id,
    _item_matches_filters,
    _normalize_item,
)


class TestCoerceGameId:
    def test_int(self):
        assert _coerce_game_id(259) == 259

    def test_string(self):
        assert _coerce_game_id('259') == 259

    def test_empty(self):
        assert _coerce_game_id(None) is None
        assert _coerce_game_id('') is None

    def test_invalid(self):
        assert _coerce_game_id('abc') is None


class TestItemMatchesFilters:
    def test_matching_sab_item(self):
        item = {'gameId': SAB_GAME_ID, 'category': 'CustomItem'}
        assert _item_matches_filters(
            item, expected_game_id=SAB_GAME_ID, expected_category='CustomItem',
        )

    def test_rejects_other_game(self):
        item = {'gameId': 16, 'category': 'CustomItem'}  # Fortnite
        assert not _item_matches_filters(
            item, expected_game_id=SAB_GAME_ID, expected_category='CustomItem',
        )

    def test_rejects_missing_game_id_when_expected(self):
        item = {'category': 'CustomItem'}
        assert not _item_matches_filters(
            item, expected_game_id=SAB_GAME_ID, expected_category='',
        )

    def test_rejects_wrong_category(self):
        item = {'gameId': SAB_GAME_ID, 'category': 'Account'}
        assert not _item_matches_filters(
            item, expected_game_id=SAB_GAME_ID, expected_category='CustomItem',
        )

    def test_category_optional(self):
        item = {'gameId': SAB_GAME_ID, 'category': 'Anything'}
        assert _item_matches_filters(
            item, expected_game_id=SAB_GAME_ID, expected_category='',
        )


class TestNormalizePreservesGameId:
    def test_wrapped_offer_keeps_game_id(self):
        entry = {
            'offer': {
                'id': 'offer-1',
                'gameId': SAB_GAME_ID,
                'category': 'CustomItem',
                'offerTitle': 'SAB Pet',
                'minPurchasePrice': {'amount': 1.5, 'currency': 'USD'},
            },
            'user': {'username': 'SellerA', 'id': 'uuid-1'},
        }
        item = _normalize_item(entry)
        assert item is not None
        assert item['gameId'] == SAB_GAME_ID
        assert item['category'] == 'CustomItem'
        assert item['_seller_username'] == 'SellerA'


class TestFetchItemsFiltersNonSab:
    def setup_method(self):
        _SELLER_UUID_CACHE.clear()

    def test_seller_uuid_fetch_drops_non_sab_items(self):
        provider = EldoradoSourceProvider(credential=MagicMock())
        _SELLER_UUID_CACHE['multiseller'] = 'seller-uuid-1'

        sab_entry = {
            'offer': {
                'id': 'sab-offer',
                'gameId': SAB_GAME_ID,
                'category': 'CustomItem',
                'offerTitle': 'SAB Brainrot',
                'minPurchasePrice': {'amount': 2.0, 'currency': 'USD'},
            },
            'user': {'username': 'MultiSeller', 'id': 'seller-uuid-1'},
        }
        fortnite_entry = {
            'offer': {
                'id': 'fn-offer',
                'gameId': 16,
                'category': 'CustomItem',
                'offerTitle': 'Fortnite Skin',
                'minPurchasePrice': {'amount': 5.0, 'currency': 'USD'},
            },
            'user': {'username': 'MultiSeller', 'id': 'seller-uuid-1'},
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            'results': [sab_entry, fortnite_entry],
            'totalPages': 1,
        }

        session = MagicMock()
        session.get.return_value = mock_resp
        provider._session = session

        pages = list(
            provider.fetch_items(
                'gameId=259&category=CustomItem',
                seller_username='MultiSeller',
            )
        )

        assert len(pages) == 1
        assert [item['id'] for item in pages[0]] == ['sab-offer']

        # API call must omit gameId when using seller UUID
        called_params = session.get.call_args.kwargs['params']
        assert called_params['userId'] == 'seller-uuid-1'
        assert 'gameId' not in called_params

    def test_defaults_to_sab_game_when_url_omits_game_id(self):
        provider = EldoradoSourceProvider(credential=MagicMock())
        _SELLER_UUID_CACHE['seller'] = 'uuid-x'

        other_game = {
            'offer': {
                'id': 'other',
                'gameId': 70,
                'category': 'CustomItem',
                'offerTitle': 'Roblox',
                'minPurchasePrice': {'amount': 1.0, 'currency': 'USD'},
            },
            'user': {'username': 'Seller', 'id': 'uuid-x'},
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {'results': [other_game], 'totalPages': 1}

        session = MagicMock()
        session.get.return_value = mock_resp
        provider._session = session

        pages = list(provider.fetch_items('', seller_username='Seller'))
        assert pages == []
