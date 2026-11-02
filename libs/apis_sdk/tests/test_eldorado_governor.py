"""Per-store Eldorado governor (2 Nov 2026 cowboy flood regression)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from apis_sdk.clients.marketplaces.eldorado.governor import (
    EldoradoGovernor,
    GovernedEldoradoFacade,
    is_governor_refusal,
    is_rate_limited,
    store_key,
)
from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.result import ApiResult


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def cowboy() -> ApiResult:
    return ApiResult.from_error(
        ErrorCategory.RATE_LIMIT, "HTTP 429", status_code=429, provider="eldorado",
        details={"code": 429, "messages": ["Whoa! Calm down, cowboy! Quota exceeded."]},
    )


@pytest.fixture
def gov(tmp_path):
    clock = Clock()
    return EldoradoGovernor(tmp_path, write_min_interval=120, clock=clock, sleep=clock.sleep), clock


def test_store_key_normalises_slugs():
    assert store_key("eldorado-ezsmurfmart") == "ezsmurfmart"
    assert store_key("Eldorado_EzSmurfShop") == "ezsmurfshop"


def test_writes_are_spaced_two_minutes_per_store(gov):
    g, clock = gov
    assert g.acquire_write("ezsmurfmart", max_wait=0) == (True, "", 0.0)
    ok, reason, wait = g.acquire_write("ezsmurfmart", max_wait=0)
    assert (ok, reason) == (False, "write_budget") and wait == pytest.approx(120)
    # The other store has its own budget.
    assert g.acquire_write("ezsmurfshop", max_wait=0)[0] is True
    # Waiting is allowed when the caller accepts it.
    assert g.acquire_write("ezsmurfmart", max_wait=130)[0] is True
    assert clock.now == pytest.approx(1_800_000_120)


def test_cowboy_ladder_is_per_store_and_reset_only_by_own_success(gov):
    g, clock = gov
    expected = [180, 360, 720, 1800, 3600]
    for pause in expected:
        assert g.record_write_result("ezsmurfmart", cowboy()) == pause
        assert g.acquire_write("ezsmurfmart", max_wait=10_000)[1] == "cowboy_cooldown"
        assert g.write_cooldown_remaining("ezsmurfshop") == 0
        g.record_write_result("ezsmurfshop", ApiResult.success({}))  # Shop success: no effect on Mart
        clock.now += pause
    g.record_write_result("ezsmurfmart", ApiResult.success({}))
    assert g.record_write_result("ezsmurfmart", cowboy()) == 180


def test_two_processes_share_one_budget(tmp_path):
    clock = Clock()
    a = EldoradoGovernor(tmp_path, write_min_interval=120, clock=clock, sleep=clock.sleep)
    b = EldoradoGovernor(tmp_path, write_min_interval=120, clock=clock, sleep=clock.sleep)
    assert a.acquire_write("ezsmurfshop", max_wait=0)[0] is True
    assert b.acquire_write("ezsmurfshop", max_wait=0)[1] == "write_budget"
    a.record_write_result("ezsmurfshop", cowboy())
    assert b.acquire_write("ezsmurfshop", max_wait=0)[1] == "cowboy_cooldown"


def test_read_429_pauses_reads_briefly_not_writes(gov):
    g, clock = gov
    g.record_read_result("ezsmurfmart", cowboy())
    assert g.admit_read("ezsmurfmart")[0] is False
    assert g.acquire_write("ezsmurfmart", max_wait=0)[0] is True
    clock.now += 60
    assert g.admit_read("ezsmurfmart")[0] is True


def test_facade_refuses_without_sending_and_counts(gov):
    g, clock = gov
    calls = []
    inner = SimpleNamespace(
        update_offer=lambda *a, **k: calls.append("update") or cowboy(),
        search_my_offers=lambda *a, **k: calls.append("search") or ApiResult.success([]),
        create_offer=lambda *a, **k: calls.append("create") or ApiResult.success({}),
    )
    facade = GovernedEldoradoFacade(inner, "eldorado-ezsmurfmart", governor=g, max_write_wait=0)
    first = facade.update_offer("x", {})
    assert is_rate_limited(first) and calls == ["update"]
    refused = facade.create_offer({})  # store now paused: nothing is sent
    assert calls == ["update"] and is_governor_refusal(refused) and not is_rate_limited(refused)
    assert facade.search_my_offers(params={}).ok  # reads continue
    hours = next(iter(g.snapshot()["ezsmurfmart"]["hours"].values()))
    assert hours["write"] == 1 and hours["write_429"] == 1 and hours["refused_cooldown"] == 1 and hours["read"] == 1


def test_rate_limit_is_never_retried_by_strategy():
    from apis_sdk.clients.marketplaces.eldorado.retry import EldoradoRetryStrategy
    from apis_sdk.core.exceptions import RateLimitError
    from apis_sdk.core.enums import RetryAction

    decision = EldoradoRetryStrategy().decide(1, RateLimitError("cowboy", provider="eldorado"))
    assert decision.action == RetryAction.NO_RETRY
