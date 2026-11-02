"""Per-store Eldorado governor (2 Nov 2026 cowboy flood regression)."""

from __future__ import annotations

import ast
import json
import multiprocessing
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from apis_sdk.clients.marketplaces.eldorado.governor import (
    READ_METHODS,
    WRITE_METHODS,
    WRITES_HELD_RETRY_SECONDS,
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


@pytest.fixture(autouse=True)
def clear_test_write_hold(monkeypatch):
    # Tests only use synthetic clients, regardless of the runner's environment.
    monkeypatch.delenv("ELDORADO_WRITES_HELD", raising=False)


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
    from apis_sdk.core.enums import RetryAction
    from apis_sdk.core.exceptions import RateLimitError

    decision = EldoradoRetryStrategy().decide(1, RateLimitError("cowboy", provider="eldorado"))
    assert decision.action == RetryAction.NO_RETRY


class SyntheticInventory:
    """Shared file inventory with intentionally unguarded whole-list updates."""

    def __init__(self, path):
        self.path = Path(path)
        self.calls = []

    def search_my_offers(self):
        self.calls.append("read")
        return ApiResult.success(json.loads(self.path.read_text()))

    def update_offer(self, offer_id, payload):
        self.calls.append("write")
        self.path.write_text(json.dumps(payload) + "\n")
        return ApiResult.success(payload)


def _inventory_worker(state_dir, inventory_path, value, ready, proceed, results, retry=None):
    """Real spawned process; lease precedes every read, including the retry."""
    os.environ.pop("ELDORADO_WRITES_HELD", None)
    inner = SyntheticInventory(inventory_path)
    facade = GovernedEldoradoFacade(
        inner, "synthetic-store", governor=EldoradoGovernor(state_dir, write_min_interval=0),
        max_write_wait=0,
    )

    def attempt(wait_before_write):
        with facade.offer_mutation("synthetic-offer") as admitted:
            if not admitted:
                # Automatic wrappers must also refuse WITHOUT reading/sending.
                refused = facade.update_offer("synthetic-offer", ["stale"])
                assert is_governor_refusal(refused)
                assert refused.error.details["governor"] == "offer_mutation_busy"
                return False
            accounts = facade.search_my_offers().data
            if wait_before_write:
                ready.set()
                assert proceed.wait(15), "first writer was not released"
            assert facade.update_offer("synthetic-offer", accounts + [value]).ok
            return True

    admitted = attempt(retry is None)
    results.put(("first" if retry is None else "busy", admitted, list(inner.calls)))
    if retry is not None:
        assert retry.wait(15), "second writer was not allowed to retry"
        results.put(("retry", attempt(False), list(inner.calls)))


def test_multiprocessing_lease_prevents_stale_inventory_overwrite(tmp_path):
    inventory = tmp_path / "inventory.json"
    inventory.write_text('["initial"]\n')
    context = multiprocessing.get_context("spawn")
    ready, release, retry = (context.Event() for _ in range(3))
    first_results, second_results = context.Queue(), context.Queue()
    first = context.Process(
        target=_inventory_worker,
        args=(tmp_path / "state", inventory, "first", ready, release, first_results),
    )
    second = context.Process(
        target=_inventory_worker,
        args=(tmp_path / "state", inventory, "second", ready, release, second_results, retry),
    )
    started = []
    try:
        first.start()
        started.append(first)
        assert ready.wait(15), "first process did not acquire/read under lease"
        second.start()
        started.append(second)
        assert second_results.get(timeout=15) == ("busy", False, [])
        assert first.is_alive()  # overlap is real, not sequential object reuse
        assert json.loads(inventory.read_text()) == ["initial"]
        release.set()
        assert first_results.get(timeout=15) == ("first", True, ["read", "write"])
        first.join(timeout=15)
        assert first.exitcode == 0
        retry.set()
        assert second_results.get(timeout=15) == ("retry", True, ["read", "write"])
        second.join(timeout=15)
        assert second.exitcode == 0
        assert json.loads(inventory.read_text()) == ["initial", "first", "second"]
    finally:
        release.set()
        retry.set()
        for process in started:
            process.join(timeout=2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        first_results.close()
        second_results.close()


def test_same_thread_nested_lease_and_wrappers_reuse_but_other_thread_cannot(tmp_path):
    calls = []
    inner = SimpleNamespace(
        update_offer=lambda *a, **k: calls.append("update") or ApiResult.success({}),
        delete_offer=lambda *a, **k: calls.append("delete") or ApiResult.success(None),
    )
    facade = GovernedEldoradoFacade(
        inner, "store", governor=EldoradoGovernor(tmp_path, write_min_interval=0),
        max_write_wait=0,
    )
    # A separate facade/governor on this thread must reuse the same file lease.
    peer = GovernedEldoradoFacade(
        inner, "eldorado-store", governor=EldoradoGovernor(tmp_path, write_min_interval=0),
        max_write_wait=0,
    )

    def other_thread():
        with facade.offer_mutation("offer") as admitted:
            assert admitted is False
        return [
            facade.update_offer("offer", {}),
            peer.delete_offer(offer_id="offer"),
        ]

    with ThreadPoolExecutor(max_workers=1) as executor:
        with facade.offer_mutation("offer") as admitted:
            assert admitted is True
            with peer.offer_mutation("offer") as nested:
                assert nested is True
                assert peer.update_offer(offer_id="offer", payload={}).ok
            refused = executor.submit(other_thread).result(timeout=5)
            assert all(is_governor_refusal(result) for result in refused)
            assert all(result.error.details["governor"] == "offer_mutation_busy" for result in refused)
            assert calls == ["update"]
            assert facade.delete_offer("offer").ok
        assert executor.submit(lambda: peer.update_offer("offer", {})).result(timeout=5).ok
    assert calls == ["update", "delete", "update"]


@pytest.mark.parametrize("method", ["update_offer", "delete_offer", "alias_update", "alias_delete"])
def test_automatic_wrapper_lease_spans_underlying_mutation(tmp_path, method):
    entered, release = threading.Event(), threading.Event()

    def mutation(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return ApiResult.success({})

    inner = SimpleNamespace(
        update_offer=mutation,
        delete_offer=lambda *a, **k: mutation(*a, **k),
        get_order_by_id=lambda *a: ApiResult.success({}),
    )
    inner.alias_update = inner.update_offer
    inner.alias_delete = inner.delete_offer
    governor = EldoradoGovernor(tmp_path, write_min_interval=0)
    facade = GovernedEldoradoFacade(inner, "store", governor=governor, max_write_wait=0)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(getattr(facade, method), offer_id="offer", payload={})
        try:
            assert entered.wait(10)
            with facade.offer_mutation("offer") as admitted:
                assert admitted is False
            assert facade.get_order_by_id("order").ok  # no read lease or hold
            refused = facade.delete_offer("offer")
            assert refused.error.details["governor"] == "offer_mutation_busy"
            hours = next(iter(governor.snapshot()["store"]["hours"].values()))
            assert hours["write"] == 1  # busy wrapper does not claim store budget
        finally:
            release.set()
        assert pending.result(timeout=10).ok
    with facade.offer_mutation("offer") as admitted:
        assert admitted is True


@pytest.mark.parametrize("method", ["update_offer", "delete_offer"])
def test_automatic_wrapper_releases_lease_when_inner_raises(tmp_path, method):
    def failed_mutation(*args, **kwargs):
        raise RuntimeError("synthetic failure")

    facade = GovernedEldoradoFacade(
        SimpleNamespace(**{method: failed_mutation}), "store",
        governor=EldoradoGovernor(tmp_path, write_min_interval=0), max_write_wait=0,
    )
    with pytest.raises(RuntimeError, match="synthetic failure"):
        getattr(facade, method)("offer", {})

    def another_thread():
        with facade.offer_mutation("offer") as admitted:
            return admitted

    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(another_thread).result(timeout=5) is True


def _fork_try_lease(facade, results):
    with facade.offer_mutation("offer") as admitted:
        results.put(admitted)


def test_forked_process_cannot_reuse_parent_thread_lease(tmp_path):
    facade = GovernedEldoradoFacade(SimpleNamespace(), "store", governor=EldoradoGovernor(tmp_path))
    context = multiprocessing.get_context("fork")
    results = context.Queue()
    with facade.offer_mutation("offer") as admitted:
        assert admitted
        process = context.Process(target=_fork_try_lease, args=(facade, results))
        process.start()
        try:
            assert results.get(timeout=10) is False
            process.join(timeout=10)
            assert process.exitcode == 0
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
    with facade.offer_mutation("offer") as admitted:
        assert admitted
    results.close()


def test_leases_are_per_store_and_offer_hashed_empty_and_release_on_exception(tmp_path):
    governor = EldoradoGovernor(tmp_path)
    facade = GovernedEldoradoFacade(SimpleNamespace(), "synthetic-store", governor=governor)
    offer_id = "synthetic/offer-with-private-identifiers"
    with pytest.raises(RuntimeError, match="caller failed"):
        with facade.offer_mutation(offer_id) as admitted:
            assert admitted
            with governor.offer_mutation("another-store", offer_id) as other_store:
                assert other_store
            with facade.offer_mutation("another-offer") as other_offer:
                assert other_offer
            raise RuntimeError("caller failed")
    with facade.offer_mutation(offer_id) as admitted:
        assert admitted
    leases = list((tmp_path / "offer-leases").iterdir())
    assert len(leases) == 3
    for lease in leases:
        assert re.fullmatch(r"[0-9a-f]{64}\.lock", lease.name)
        assert lease.read_bytes() == b""
        assert lease.stat().st_mode & 0o777 == 0o600


def test_unavailable_lease_storage_fails_closed_without_writes(tmp_path):
    (tmp_path / "offer-leases").write_text("not a directory\n")
    calls = []
    facade = GovernedEldoradoFacade(
        SimpleNamespace(update_offer=lambda *a: calls.append("write")),
        "store", governor=EldoradoGovernor(tmp_path), max_write_wait=0,
    )
    with facade.offer_mutation("offer") as admitted:
        assert admitted is False
    assert is_governor_refusal(facade.update_offer("offer", {}))
    assert calls == []
    assert facade.seconds_until_write() == 0  # lease refusal did not claim budget


@pytest.mark.parametrize("value", [
    "true", "1", "yes", "on", " TRUE ", "Yes", "ON", "tru", "unexpected", "2",
])
def test_write_hold_blocks_admission_and_claims_but_not_reads(gov, monkeypatch, value):
    governor, clock = gov
    facade = GovernedEldoradoFacade(SimpleNamespace(), "store", governor=governor)
    monkeypatch.setenv("ELDORADO_WRITES_HELD", value)
    assert governor.writes_held() and facade.writes_held()
    assert governor.seconds_until_write("store") == WRITES_HELD_RETRY_SECONDS
    assert facade.seconds_until_write() == WRITES_HELD_RETRY_SECONDS
    assert governor.acquire_write("store", max_wait=WRITES_HELD_RETRY_SECONDS * 2) == (
        False, "writes_held", WRITES_HELD_RETRY_SECONDS,
    )
    with facade.offer_mutation("offer") as admitted:
        assert admitted is False
    assert clock.now == 1_800_000_000.0
    assert not governor._dir.exists() or not list(governor._dir.glob("*.json"))
    assert governor.admit_read("store")[0] is True
    monkeypatch.setenv("ELDORADO_WRITES_HELD", "false")
    assert not facade.writes_held()
    assert facade.seconds_until_write() == 0
    assert governor.acquire_write("store", max_wait=0)[0] is True


@pytest.mark.parametrize("value", ["", " ", "false", "0", "no", "off", " FALSE ", "No", "OFF"])
def test_write_hold_only_explicit_disable_values_allow_admission(gov, monkeypatch, value):
    governor, clock = gov
    monkeypatch.setenv("ELDORADO_WRITES_HELD", value)
    assert governor.writes_held() is False
    assert governor.seconds_until_write("store") == 0
    assert governor.acquire_write("store", max_wait=0)[0] is True


def test_all_discovered_facade_mutations_and_aliases_are_held_but_gets_allowed(gov, monkeypatch):
    # Discover public API from source: importing the real facade requires optional
    # runtime dependencies, and this test must never instantiate a live client.
    import apis_sdk.clients.marketplaces.eldorado.governor as governor_module

    source = Path(governor_module.__file__).with_name("facade.py")
    facade_class = next(
        node for node in ast.parse(source.read_text()).body
        if isinstance(node, ast.ClassDef) and node.name == "EldoradoFacade"
    )
    methods = {
        node.name for node in facade_class.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }
    reads = {name for name in methods if name.startswith(("get_", "search_"))}
    mutations = methods - reads
    assert reads <= READ_METHODS
    assert mutations <= WRITE_METHODS
    assert {"upload_image", "deliver_order", "create_offer", "update_offer", "delete_offer"} <= mutations
    calls = []

    def stub(name):
        def call(*args, **kwargs):
            calls.append(name)
            return ApiResult.success({})
        return call

    # Include unknown status/feedback operations to check future mutations fail
    # closed too, and aliases with no mutating verb in their name.
    future_mutations = {"update_order_status", "set_order_status", "submit_order_feedback"}
    inner = SimpleNamespace(**{name: stub(name) for name in methods | future_mutations})
    for name in mutations | future_mutations:
        setattr(inner, f"alias_{name}", getattr(inner, name))
    inner.fetch_orders = inner.get_seller_orders  # alias of a known GET
    governor, clock = gov
    facade = GovernedEldoradoFacade(inner, "store", governor=governor, max_write_wait=0)
    cached_update = facade.update_offer  # hold is checked at call time, not lookup
    monkeypatch.setenv("ELDORADO_WRITES_HELD", "true")
    for name in mutations | future_mutations:
        for call_name in (name, f"alias_{name}"):
            result = getattr(facade, call_name)()
            assert is_governor_refusal(result), call_name
            assert not is_rate_limited(result)
            assert result.error.details["governor"] == "writes_held"
    assert is_governor_refusal(cached_update("offer", {}))
    assert calls == []
    for name in sorted(reads):
        assert getattr(facade, name)().ok
    assert facade.fetch_orders().ok
    assert calls == sorted(reads) + ["get_seller_orders"]
    assert "next_write_at" not in governor.snapshot()["store"]


def test_hold_changed_during_budget_wait_prevents_write(gov, monkeypatch):
    governor, clock = gov
    calls = []
    assert governor.acquire_write("store", max_wait=0)[0]

    def hold_during_sleep(seconds):
        clock.sleep(seconds)
        monkeypatch.setenv("ELDORADO_WRITES_HELD", "on")

    governor._sleep = hold_during_sleep
    facade = GovernedEldoradoFacade(
        SimpleNamespace(update_offer=lambda *a: calls.append("write")),
        "store", governor=governor, max_write_wait=130,
    )
    with facade.offer_mutation("offer") as admitted:
        assert admitted
        result = facade.update_offer("offer", {})
    assert is_governor_refusal(result)
    assert result.error.details["governor"] == "writes_held"
    assert calls == []
    hours = next(iter(governor.snapshot()["store"]["hours"].values()))
    assert hours["write"] == 1  # the held attempt never claimed a second slot


def test_outer_offer_lease_does_not_bypass_existing_store_spacing(gov):
    governor, clock = gov
    calls = []
    facade = GovernedEldoradoFacade(
        SimpleNamespace(update_offer=lambda *a: calls.append("write") or ApiResult.success({})),
        "store", governor=governor, max_write_wait=0,
    )
    with facade.offer_mutation("offer") as admitted:
        assert admitted
        assert facade.update_offer("offer", {}).ok
        refused = facade.update_offer("offer", {})
        assert refused.error.details["governor"] == "write_budget"
    assert calls == ["write"]
