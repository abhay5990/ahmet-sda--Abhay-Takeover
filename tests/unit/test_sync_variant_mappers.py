"""Unit tests for marketplace offer-sync variant mappers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

from apps.sync.services.gameboost.offers import mapper as gameboost_mapper
from apps.sync.services.playerauctions.offers import mapper as pa_mapper


def test_gameboost_valorant_extracts_region_platform_composite() -> None:
    payload = {
        'parameters': {
            'server': 'Asia Pacific',
            'platforms': ['PC'],
        },
    }

    assert gameboost_mapper.extract_variant(
        payload,
        game_slug='valorant',
    ) == 'ap-pc'


def test_gameboost_platform_games_extract_platform_slug() -> None:
    payload = {'parameters': {'platform': 'PlayStation'}}

    assert gameboost_mapper.extract_variant(payload) == 'psn'


def test_playerauctions_valorant_extracts_region_with_implicit_pc() -> None:
    payload = {'details': {'serverId': 9128}}

    assert pa_mapper.extract_variant(
        payload,
        game_slug='valorant',
    ) == 'eu-pc'


def test_playerauctions_platform_games_extract_platform_slug() -> None:
    assert pa_mapper.extract_variant(
        {'details': {'serverId': 7775}},
        game_slug='rainbow-six-siege',
    ) == 'psn'
    assert pa_mapper.extract_variant(
        {'details': {'serverId': 7877}},
        game_slug='fortnite',
    ) == 'pc'


def test_playerauctions_gtav_fallback_extracts_canonical_slug() -> None:
    assert pa_mapper.extract_variant(
        {'details': {'serverId': 9874}},
        game_slug='grand-theft-auto-5',
    ) == 'ps5'
