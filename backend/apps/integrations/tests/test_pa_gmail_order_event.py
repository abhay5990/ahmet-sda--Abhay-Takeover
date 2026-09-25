from __future__ import annotations

import hashlib
import hmac
import json
import uuid

from apps.integrations.api.pa_gmail_order_event import (
    SIGNATURE_VERSION,
    canonical_payload_json,
    parse_payload,
    signature_is_valid,
)


SECRET = 'A' * 48


def _payload():
    return {
        'eventId': str(uuid.uuid4()),
        'source': 'codetracker-pa-gmail',
        'orderId': '16523033',
        'code': '#GNK1FI',
        'market': 'GTA 5 Online - PS5',
        'automaticDelivery': True,
        'observedAt': 1_790_000_000_000,
    }


def test_accepts_only_minimal_signed_contract():
    parsed = parse_payload(json.dumps(_payload()).encode('utf-8'))
    timestamp = '1790000000123'
    signature = hmac.new(
        SECRET.encode('utf-8'),
        f'{SIGNATURE_VERSION}.{timestamp}.'.encode('utf-8') + canonical_payload_json(parsed),
        hashlib.sha256,
    ).hexdigest()
    assert signature_is_valid(
        payload=parsed,
        timestamp=timestamp,
        supplied_signature=signature,
        secret=SECRET,
    ) is True
    assert signature_is_valid(
        payload={**parsed, 'code': '#OTHER1'},
        timestamp=timestamp,
        supplied_signature=signature,
        secret=SECRET,
    ) is False


def test_rejects_unexpected_or_sensitive_fields():
    payload = _payload()
    payload['emailBody'] = 'must never cross the bridge'
    try:
        parse_payload(json.dumps(payload).encode('utf-8'))
    except ValueError as exc:
        assert str(exc) == 'unexpected event fields'
    else:
        raise AssertionError('unexpected event fields must be rejected')


def test_normalizes_only_valid_visible_tracking_codes():
    payload = _payload()
    payload['code'] = '#gnk1fi'
    assert parse_payload(json.dumps(payload).encode('utf-8'))['code'] == '#GNK1FI'
    payload['code'] = 'not-a-code'
    try:
        parse_payload(json.dumps(payload).encode('utf-8'))
    except ValueError as exc:
        assert str(exc) == 'invalid tracking code'
    else:
        raise AssertionError('malformed codes must be rejected')


def test_sda_receiver_excludes_codetracker_owned_games():
    from pathlib import Path

    source = Path('backend/apps/integrations/api/pa_gmail_order_event.py').read_text()
    assert '_CODETRACKER_OWNED_GAME_SLUGS' in source
    assert ".exclude(game__slug__in=_CODETRACKER_OWNED_GAME_SLUGS)" in source


def test_sda_receiver_accepts_the_deployed_mart_slug_and_repairs_only_prior_unmatched_events():
    from pathlib import Path

    source = Path('backend/apps/integrations/api/pa_gmail_order_event.py').read_text()
    assert "'playerauctions-csgosmurfkings'" in source
    assert "if event.disposition != PaGmailOrderEvent.Disposition.UNMATCHED or event.order_id:" in source
    assert 'repaired = recover_unmatched_event(event=existing)' in source
    assert "event.save(update_fields=['integration_account', 'listing', 'order', 'disposition', 'updated_at'])" in source


def test_sda_receiver_closes_only_the_exact_matched_local_listing():
    from pathlib import Path

    source = Path('backend/apps/integrations/api/pa_gmail_order_event.py').read_text()
    assert 'if listing.status != ListingStatus.CLOSED:' in source
    assert 'listing.status = ListingStatus.CLOSED' in source
    assert "listing.save(update_fields=['status', 'removed_at', 'updated_at'])" in source
    assert 'no PA offer mutation or deletion' in source
