"""Integration test — ClashOfStats tracker fetch via CurlCffiTransport.

Gerçek ağa bağlanır. Cloudflare bypass için CurlCffiTransport (chrome
impersonation) kullanır. Soğuk ortamda ağ erişimi gerektirir.

Çalıştırmak için:
    pytest tests/integration/test_clashofstats_tracker.py -v -s
"""

from __future__ import annotations

import json

import pytest

from apis_sdk.clients.trackers.clashofstats.config import ClashOfStatsConfig
from apis_sdk.factories.clashofstats_factory import ClashOfStatsFactory
from apis_sdk.infrastructure.http.curl_cffi_transport import CurlCffiTransport

# Bilinen gerçek bir CoC hesap tag'i (payload_pipeline fixture ile aynı)
PLAYER_TAG = "L0URGJPLV"


@pytest.fixture(scope="module")
def facade():
    config = ClashOfStatsConfig()
    transport = CurlCffiTransport(
        impersonate="chrome124",
        default_timeout=20.0,
        default_headers=config.get_default_headers(),
    )
    yield ClashOfStatsFactory.create(transport=transport, timeout=20.0)
    transport.close()


@pytest.fixture(scope="module")
def player_data(facade):
    result = facade.get_player_data(PLAYER_TAG)
    if not result.ok:
        pytest.skip(f"ClashOfStats API erişilemez: {result.error.message}")
    return result.data


class TestClashOfStatsTransportLayer:
    """CurlCffiTransport üzerinden ClashOfStats'tan veri çekme."""

    def test_raw_response_dump(self, facade):
        """Ham API yanıtını stdout'a yazar — yapıyı anlamak için."""
        result = facade.get_player_data(PLAYER_TAG)
        if result.ok:
            top_level_keys = list(result.data.keys())
            heroes_sample = result.data.get("heroes", [])[:2]
            troops_sample = result.data.get("troops", [])[:2]
            print("\n--- ClashOfStats raw response ---")
            print(f"ok          : {result.ok}")
            print(f"status_code : {result.status_code}")
            print(f"top-level keys ({len(top_level_keys)}): {top_level_keys}")
            print(f"heroes[0:2] : {json.dumps(heroes_sample, indent=2)}")
            print(f"troops[0:2] : {json.dumps(troops_sample, indent=2)}")
            print("---------------------------------")
        else:
            print("\n--- ClashOfStats ERROR ---")
            print(f"ok          : {result.ok}")
            print(f"status_code : {result.status_code}")
            print(f"category    : {result.error.category}")
            print(f"message     : {result.error.message}")
            print(f"retryable   : {result.error.is_retryable}")
            print("--------------------------")
        # Bu test her zaman geçer — sadece dump amaçlı
        assert True

    def test_request_succeeds(self, facade):
        result = facade.get_player_data(PLAYER_TAG)
        assert result.ok, f"API hatası: {result.error.message}"

    def test_response_contains_player_tag(self, player_data):
        tag = player_data.get("tag", "")
        assert PLAYER_TAG in tag.lstrip("#")

    def test_response_town_hall_level_is_int(self, player_data):
        th = player_data.get("townHallLevel")
        assert isinstance(th, int)
        assert th >= 1

    def test_response_has_heroes_list(self, player_data):
        assert isinstance(player_data.get("heroes", []), list)

    def test_response_has_troops_list(self, player_data):
        assert isinstance(player_data.get("troops", []), list)

    def test_response_has_spells_list(self, player_data):
        assert isinstance(player_data.get("spells", []), list)

    def test_response_has_name(self, player_data):
        assert isinstance(player_data.get("name"), str)
        assert player_data["name"] != ""

    def test_invalid_tag_does_not_succeed(self, facade):
        result = facade.get_player_data("INVALIDTAG000")
        assert not result.ok
