"""Unit tests for Eldorado tradeEnvironment variant extraction."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

from apps.sync.services.eldorado.offers.mapper import extract_variant


def test_extract_variant_resolves_composite_ids_by_dimension() -> None:
    item = {
        'tradeEnvironmentValues': [
            {'id': '5', 'name': 'Region', 'value': 'AP'},
            {'id': '5-0', 'name': 'Device', 'value': 'PC'},
        ],
    }
    lookup = {
        'region': {'5': 'ap'},
        'platform': {'0': 'pc'},
    }

    assert extract_variant(item, slug_lookup=lookup) == 'ap-pc'


def test_extract_variant_does_not_confuse_colliding_external_ids() -> None:
    item = {
        'tradeEnvironmentValues': [
            {'id': '1', 'name': 'Region', 'value': 'EU'},
            {'id': '1-1', 'name': 'Device', 'value': 'PlayStation'},
        ],
    }
    lookup = {
        'region': {'1': 'eu'},
        'platform': {'1': 'psn'},
    }

    assert extract_variant(item, slug_lookup=lookup) == 'eu-psn'


def test_extract_variant_falls_back_to_value_normalization() -> None:
    item = {
        'tradeEnvironmentValues': [
            {'id': '5', 'name': 'Region', 'value': 'EU/TR/MENA/CIS'},
            {'id': '5-2', 'name': 'Device', 'value': 'Xbox'},
        ],
    }

    assert extract_variant(item) == 'eu-xbox'
