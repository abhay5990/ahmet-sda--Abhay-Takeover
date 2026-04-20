from __future__ import annotations

from payload_pipeline.core.contracts import MediaBundle, PipelineRequest
from payload_pipeline.games.r6.account import (
    R6Composer,
    R6LztSourceAdapter,
    R6Resolver,
    R6TrackerSourceAdapter,
)


def test_lzt_source_normalization_ignores_gold_dust_rank_noise(load_fixture) -> None:
    source = R6LztSourceAdapter().parse(load_fixture("lzt_r6.json"))

    assert source is not None
    # Title "...Solar Raid Diamond..." → Diamond extracted, Gold Dust filtered
    assert source.title_rank_hint == "Diamond"
    assert source.title_rank_count_hint == 1
    # lzt_rank from uplayR6Rank="Copper 4", lzt_title from "Solar Raid Diamond"
    assert [(signal.rank, signal.count, signal.season) for signal in source.rank_signals] == [
        ("Copper", 1, ""),
        ("Diamond", 1, "Solar Raid"),
    ]
    assert source.skin_count == 1168
    assert len(source.weapon_skins) == 1168


def test_tracker_source_normalization_builds_weapon_skin_records_and_rank_history(load_fixture) -> None:
    source = R6TrackerSourceAdapter().parse(load_fixture("tracker_r6.json"))

    assert source is not None
    # Last charm is "Bronze (Prep Phase)"
    assert source.rank_signals[-1].rank == "Bronze"
    assert source.rank_signals[-1].season == "Prep Phase"
    assert source.rank_signals[-1].source == "tracker_charm"
    assert source.rank_signals[-1].is_current_candidate is True
    # F2 is in "Black Ices" category in this data set
    assert any(
        skin.name == "F2" and skin.bucket == "black_ice" and skin.category == "Black Ices"
        for skin in source.weapon_skins
    )
    assert all(skin.category != "Attachment Skins" for skin in source.weapon_skins)
    assert all("uniform" not in skin.name.lower() for skin in source.weapon_skins)


def test_r6_resolver_and_composer_use_normalized_contract(load_fixture) -> None:
    request = PipelineRequest(
        game="rainbow-six-siege",
        kind="dropshipping",
        sources={
            "lzt": load_fixture("lzt_r6.json"),
            "tracker": load_fixture("tracker_r6.json"),
        },
    )

    account = R6Resolver().resolve(request)
    listing = R6Composer().compose(account, request, MediaBundle())

    # Tracker last charm "Bronze (Prep Phase)" wins current rank
    assert account.current_rank == "Bronze"
    assert account.current_rank_source == "tracker_charm"
    # Peak from tracker charms: Diamond (Solar Raid), 1x
    assert account.peak_rank == "Diamond"
    assert account.peak_rank_count == 1
    assert account.peak_rank_source == "tracker_charm"
    assert account.skin_count == 1168
    assert account.black_ice_count == 49
    assert account.operator_count == 74

    assert "Diamond" in listing.default.title
    assert "1168 Skins" in listing.default.title
    assert "Skin Count: 1168" in listing.default.description
