"""Unit tests for marketplace raw_data normalization helpers.

Usage:
    cd backend && python -m pytest ../tests/unit/test_marketplace_raw_data.py -v
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'libs' / 'apis_sdk'))

from django.conf import settings

if not settings.configured:
    settings.configure(USE_TZ=True)

from core.marketplace.enrichment import (
    build_eldorado_credential_entries,
    build_gameboost_credential_entries,
    collect_credential_entries,
)
from core.marketplace.normalizers import normalize_offer_response
from core.marketplace.payload_extractor import extract_create_payload


@dataclass
class FakeResult:
    ok: bool
    data: dict | None = None


class FakeClient:
    def __init__(self, details: dict | None):
        self.details = details
        self.calls: list[tuple[str, str | None]] = []

    def get_offer_details(self, *, offer_id: str, proxy_group: str | None = None):
        self.calls.append((offer_id, proxy_group))
        return FakeResult(ok=bool(self.details), data=self.details)


class FakeModel:
    def model_dump(self):
        return {'id': 1, 'secretDetails': 'a:b'}


def test_enrichment_builds_placeholder_entries():
    assert build_eldorado_credential_entries(['a:b', '']) == [
        {'id': '', 'secretDetails': 'a:b'},
    ]
    assert build_gameboost_credential_entries(['u:p'], account_offer_id='42') == [
        {
            'id': 0,
            'credentials': 'u:p',
            'account_offer_id': 42,
            'account_order_id': None,
            'is_sold': False,
        },
    ]
    assert collect_credential_entries([FakeModel(), {'id': 2}]) == [
        {'id': 1, 'secretDetails': 'a:b'},
        {'id': 2},
    ]


def test_normalize_eldorado_keeps_flat_response_and_adds_credentials():
    raw = normalize_offer_response(
        'eldorado',
        {'id': 'offer-1', 'offerTitle': 'Title'},
        payload={'accountSecretDetails': ['login:pass']},
    )

    assert raw['id'] == 'offer-1'
    assert raw['_credential_entries'] == [
        {'id': '', 'secretDetails': 'login:pass'},
    ]


def test_normalize_gameboost_unwraps_data_and_adds_credential_entries():
    raw = normalize_offer_response(
        'gameboost',
        {'data': {'id': 123, 'title': 'Offer'}},
        payload={'credentials': ['Login: u\nPassword: p']},
    )

    assert raw['id'] == 123
    assert raw['_credential_entries'][0]['account_offer_id'] == 123
    assert raw['_credential_entries'][0]['credentials'] == 'Login: u\nPassword: p'


def test_normalize_playerauctions_fetches_details_and_uses_bulk_title_fallback():
    details = {
        'gameId': 3637,
        'isAuto': True,
        'price': '12.5',
        'offerDuration': '30',
        'autoDelivery': {'loginName': 'u', 'password': 'p'},
    }
    client = FakeClient(details)

    raw = normalize_offer_response(
        'playerauctions',
        {'offer_id': '999'},
        payload={'Title': 'Bulk title'},
        client=client,
        proxy_group='pa-store',
    )

    assert raw['offer_id'] == 999
    assert raw['title'] == 'Bulk title'
    assert raw['total_price'] == '$12.50'
    assert raw['delivery_guarantee'] == 'Instant'
    assert raw['details'] == details
    assert client.calls == [('999', 'pa-store')]


def test_extract_create_payload_blocks_playerauctions_excel_row_without_details():
    raw = {
        'payload': {'Title': 'Excel row'},
        'response': {'offer_id': 111},
    }

    assert extract_create_payload(raw, 'playerauctions') is None


def test_extract_create_payload_refetches_playerauctions_details_for_excel_row():
    raw = {
        'payload': {'Title': 'Excel row'},
        'response': {'offer_id': 111},
    }
    client = FakeClient({
        'gameId': 3637,
        'serverId': 4144,
        'categoryId': 4144,
        'price': 10,
        'isAuto': True,
        'autoDelivery': {'loginName': 'u', 'password': 'p'},
    })

    payload = extract_create_payload(raw, 'playerauctions', client=client)

    assert payload is not None
    assert payload['gameId'] == 3637
    assert payload['title'] == 'Excel row'
    assert payload['autoDelivery']['loginName'] == 'u'
    assert client.calls == [('111', None)]


def test_extract_create_payload_uses_sync_gameboost_price_before_usd():
    raw = {
        'game': {'slug': 'league-of-legends'},
        'title': 'Offer',
        'price': {'value': 10.0},
        'price_usd': {'value': 99.0},
        '_credential_entries': [{'credentials': 'Login: u\nPassword: p'}],
    }

    payload = extract_create_payload(raw, 'gameboost')

    assert payload is not None
    assert payload['price'] == 10.0
    assert payload['credentials'] == ['Login: u\nPassword: p']


# ---------------------------------------------------------------------------
# Sync → normalize consistency tests
# ---------------------------------------------------------------------------


def test_normalize_eldorado_sync_data_preserves_all_fields():
    """Sync-enriched Eldorado data passes through normalizer unchanged."""
    sync_data = {
        'id': 'abc-123',
        'gameId': '456',
        'offerTitle': 'Fortnite Account',
        'offerState': 'Active',
        'guaranteedDeliveryTime': 'Instant',
        'pricePerUnit': {'amount': 25.0, 'currency': 'USD'},
        'expireDate': '2026-06-15T12:00:00Z',
        'tradeEnvironmentValues': [{'value': 'PC'}],
        'category': 'Account',
        '_credential_entries': [
            {'id': 'e1', 'secretDetails': 'Login: user\nPassword: pass'},
        ],
    }

    raw = normalize_offer_response('eldorado', sync_data)

    assert raw['id'] == 'abc-123'
    assert raw['offerTitle'] == 'Fortnite Account'
    assert raw['offerState'] == 'Active'
    assert raw['_credential_entries'] == sync_data['_credential_entries']
    # Normalizer should NOT overwrite existing credential entries
    assert len(raw['_credential_entries']) == 1


def test_normalize_gameboost_sync_data_no_data_wrapper():
    """Sync Gameboost data has no .data wrapper — normalizer copies as-is."""
    sync_data = {
        'id': 789,
        'game': {'id': '10'},
        'title': 'LoL Account',
        'status': 'listed',
        'price': {'value': 15.0, 'currency': {'code': 'EUR'}},
        'price_usd': {'value': 18.0},
        'parameters': {'platform': 'PC'},
        '_credential_entries': [
            {'id': 0, 'credentials': 'Login: u\nPassword: p',
             'account_offer_id': 789, 'account_order_id': None,
             'is_sold': False},
        ],
    }

    raw = normalize_offer_response('gameboost', sync_data)

    assert raw['id'] == 789
    assert raw['title'] == 'LoL Account'
    assert raw['game'] == {'id': '10'}
    assert raw['_credential_entries'] == sync_data['_credential_entries']


def test_normalize_pa_sync_data_preserves_existing_details():
    """Sync PA data with pre-enriched details should NOT trigger API fetch."""
    sync_data = {
        'offer_id': 555,
        'title': 'Valorant Account',
        'system_status': 'Hidden',
        'total_price': '$19.99',
        'delivery_guarantee': 'Instant',
        'expired_time_string': 'Jun-01-2026 08:30:00 PM',
        'details': {
            'gameId': 3637,
            'isAuto': True,
            'price': 19.99,
            'offerDuration': 30,
            'serverId': '9874',
            'autoDelivery': {'loginName': 'u', 'password': 'p'},
        },
    }

    # No client — must NOT lose details
    raw = normalize_offer_response('playerauctions', sync_data)

    assert raw['offer_id'] == 555
    assert raw['system_status'] == 'Hidden'  # preserved, not hardcoded "Active"
    assert raw['title'] == 'Valorant Account'
    assert raw['details'] == sync_data['details']
    assert raw['total_price'] == '$19.99'
    assert raw['delivery_guarantee'] == 'Instant'
    assert raw['expired_time_string'] == 'Jun-01-2026 08:30:00 PM'  # preserved


def test_normalize_pa_sync_data_no_api_call_when_details_present():
    """When details already exist, normalizer must not call client."""
    sync_data = {
        'offer_id': 777,
        'title': 'GTA V Account',
        'system_status': 'Active',
        'total_price': '$10.00',
        'delivery_guarantee': 'Instant',
        'expired_time_string': 'Jul-15-2026 03:00:00 PM',
        'details': {
            'gameId': 5000,
            'isAuto': True,
            'price': 10.0,
            'offerDuration': 30,
        },
    }

    client = FakeClient({'gameId': 9999})  # would return different data
    raw = normalize_offer_response(
        'playerauctions', sync_data, client=client,
    )

    # Client should NOT be called because details already exist
    assert client.calls == []
    assert raw['details']['gameId'] == 5000  # original, not 9999


def test_normalize_pa_without_details_falls_back_to_fetch():
    """PA data without details should still fetch from client (posting flow)."""
    details = {
        'gameId': 3637,
        'isAuto': False,
        'price': 5.0,
        'offerDuration': 14,
    }
    client = FakeClient(details)

    raw = normalize_offer_response(
        'playerauctions',
        {'offer_id': '100', 'title': 'New Offer'},
        client=client,
    )

    assert client.calls == [('100', None)]
    assert raw['details'] == details
    assert raw['delivery_guarantee'] == ''  # isAuto=False


def test_normalize_pa_without_details_no_client_preserves_existing_fields():
    """PA data without details or client preserves whatever data exists."""
    data = {
        'offer_id': 200,
        'title': 'Some Offer',
        'system_status': 'Active',
        'total_price': '$15.00',
        'delivery_guarantee': 'Instant',
        'expired_time_string': 'Aug-01-2026 12:00:00 PM',
    }

    raw = normalize_offer_response('playerauctions', data)

    assert raw['offer_id'] == 200
    assert raw['total_price'] == '$15.00'
    assert raw['delivery_guarantee'] == 'Instant'
    assert raw['expired_time_string'] == 'Aug-01-2026 12:00:00 PM'
    assert 'details' not in raw


def test_eldorado_sync_and_posting_produce_same_shape():
    """Eldorado: sync-style and posting-style data have same key structure."""
    # Posting flow (create response + payload)
    posting_raw = normalize_offer_response(
        'eldorado',
        {'id': 'x', 'offerTitle': 'T', 'gameId': '1'},
        payload={'accountSecretDetails': ['cred1']},
    )

    # Sync flow (enriched API response, no payload)
    sync_raw = normalize_offer_response(
        'eldorado',
        {
            'id': 'y', 'offerTitle': 'T2', 'gameId': '2',
            '_credential_entries': [{'id': 'e1', 'secretDetails': 'cred2'}],
        },
    )

    # Both should have _credential_entries
    assert '_credential_entries' in posting_raw
    assert '_credential_entries' in sync_raw


def test_gameboost_sync_and_posting_produce_same_shape():
    """Gameboost: sync-style (no wrapper) and posting-style (.data wrapper) both work."""
    # Posting flow (create response wraps in .data)
    posting_raw = normalize_offer_response(
        'gameboost',
        {'data': {'id': 100, 'title': 'P'}},
        payload={'credentials': ['cred']},
    )

    # Sync flow (no .data wrapper)
    sync_raw = normalize_offer_response(
        'gameboost',
        {
            'id': 200, 'title': 'S',
            '_credential_entries': [
                {'id': 0, 'credentials': 'cred',
                 'account_offer_id': 200,
                 'account_order_id': None, 'is_sold': False},
            ],
        },
    )

    # Both should have id at top level and _credential_entries
    assert 'id' in posting_raw
    assert 'id' in sync_raw
    assert '_credential_entries' in posting_raw
    assert '_credential_entries' in sync_raw
