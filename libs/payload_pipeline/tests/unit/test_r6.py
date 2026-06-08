from __future__ import annotations

from payload_pipeline.core.contracts import MediaBundle, PipelineRequest
from payload_pipeline.games.r6.account import (
    R6Composer,
    R6LztSourceAdapter,
    R6Resolver,
    R6TrackerSourceAdapter,
)


def test_lzt_source_normalization_parses_rank_and_skins(load_fixture) -> None:
    source = R6LztSourceAdapter().parse(load_fixture("lzt_r6.json"))

    assert source is not None
    # Title has no rank mentions (only cosmetic keywords like "Black Ices", "Pro league")
    assert source.title_rank_hint == ""
    assert source.title_rank_count_hint == 0
    # lzt_rank from uplayR6Rank="Copper 5", no title rank signals
    assert [(signal.rank, signal.count, signal.season) for signal in source.rank_signals] == [
        ("Copper", 1, ""),
    ]
    assert source.skin_count == 275
    assert len(source.weapon_skins) == 275


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
    assert account.skin_count == 275
    assert account.black_ice_count == 49
    assert account.operator_count == 74

    assert "Diamond" in listing.default.title
    assert "275 Skins" in listing.default.title
    assert "Skin Count: 275" in listing.default.description


# ---------------------------------------------------------------------------
# Dropship listing item tests (real LZT data, no credentials)
# ---------------------------------------------------------------------------

def test_lzt_dropship_item_parses_tracker_url_from_description(load_fixture) -> None:
    """Real dropship item: no uplay_id/tracker_link fields, tracker URL in descriptionPlain."""
    source = R6LztSourceAdapter().parse(load_fixture("lzt_r6_dropship.json"))

    assert source is not None
    assert source.uplay_id == ""
    assert source.tracker_url == "r6skins.locker/profile/d2262a5b-d6c4-4030-8059-3f3ad4c0c9e4"
    assert source.level == 52
    assert source.skin_count == 5
    assert source.operator_count == 14


def test_lzt_dropship_item_parses_psn_connected(load_fixture) -> None:
    """Real dropship item: PSN linked via uplayLinkedAccounts."""
    source = R6LztSourceAdapter().parse(load_fixture("lzt_r6_dropship.json"))

    assert source is not None
    assert source.psn_connected is True
    assert source.xbox_connected is False


def test_r6_resolver_tracker_url_from_description_plain(load_fixture) -> None:
    """Resolver picks up tracker_url extracted from descriptionPlain."""
    request = PipelineRequest(
        game="rainbow-six-siege",
        kind="dropshipping",
        sources={"lzt": load_fixture("lzt_r6_dropship.json")},
    )
    account = R6Resolver().resolve(request)

    assert account.tracker_url == "r6skins.locker/profile/d2262a5b-d6c4-4030-8059-3f3ad4c0c9e4"


def test_r6_resolver_lzt_only_dropship_resolves_rank_from_title(load_fixture) -> None:
    """Real dropship data: uplay_r6_rank=0 (Unranked direct field), Silver from title."""
    request = PipelineRequest(
        game="rainbow-six-siege",
        kind="dropshipping",
        sources={"lzt": load_fixture("lzt_r6_dropship.json")},
    )
    account = R6Resolver().resolve(request)

    # uplay_r6_rank=0 is falsy → no lzt_rank signal → Unranked
    assert account.current_rank == "Unranked"
    # Title "Silver Y1S3" → peak rank via lzt_title signal
    assert account.peak_rank == "Silver"
    assert account.level == 52


