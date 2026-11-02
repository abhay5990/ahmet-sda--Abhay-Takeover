"""
Per-store Eldorado traffic governor, shared by every SDA process.

Why this exists (2 Nov 2026): Eldorado limits each seller account
("Whoa! Calm down, cowboy! Quota exceeded."). SDA and MCT post to the SAME two
seller accounts (ezsmurfmart / ezsmurfshop). SDA's pool restocker had no
brakes: it sent 300-1,200 failing creates/updates per hour, ignored the
cowboy replies, and so blocked MCT's normal listings on both stores.

Rules enforced here, per Eldorado store:

* Writes (create / update / delete offer) are spaced at least
  ``ELDORADO_WRITE_MIN_INTERVAL_SECONDS`` apart (default 120 s → max 30/hour).
* A cowboy/429 on any write pauses that store's writes for 3 → 6 → 12 → 30
  minutes on consecutive hits, and 60 minutes from the 5th. Only that store's
  own successful write resets the ladder. Other stores are not affected.
* A 429 on a read pauses that store's reads for 60 s (writes keep their own
  ladder), so order sync keeps working.
* While paused, calls are refused locally (no HTTP request is made) with a
  RATE_LIMIT ``ApiResult`` whose ``details["governor"]`` says why.
* Every request is counted per store per hour (reads, writes, 429s, refusals)
  so the real traffic can be checked: ``manage.py eldorado_traffic``.

State is a small JSON file per store guarded by ``fcntl.flock`` so gunicorn,
the scheduler and the dropship worker on the same host share one budget.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Iterator

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.result import ApiResult

WRITE_METHODS = frozenset({"create_offer", "update_offer", "delete_offer"})
COWBOY_BACKOFF_SECONDS = (180, 360, 720, 1800)
COWBOY_CIRCUIT_THRESHOLD = 5
COWBOY_CIRCUIT_SECONDS = 3600
READ_COOLDOWN_SECONDS = 60
DEFAULT_WRITE_MIN_INTERVAL_SECONDS = 120
DEFAULT_MAX_WRITE_WAIT_SECONDS = 130
HOURS_KEPT = 72


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
        return value if value >= 0 else default
    except ValueError:
        return default


def default_state_dir() -> Path:
    raw = os.environ.get("ELDORADO_GOVERNOR_DIR", "").strip()
    return Path(raw) if raw else Path.home() / ".cache" / "sda-eldorado-governor"


def store_key(raw: str | None) -> str:
    """Normalise a store slug/name to one key ("eldorado-ezsmurfmart" → "ezsmurfmart")."""
    key = str(raw or "").strip().lower().replace("_", "-")
    key = re.sub(r"^eldorado-", "", key)
    return re.sub(r"[^a-z0-9.-]", "", key) or "unknown"


def is_rate_limited(result: Any) -> bool:
    """True for a real Eldorado 429 / cowboy reply (not a local governor refusal)."""
    error = getattr(result, "error", None)
    if result is None or getattr(result, "ok", True) or error is None:
        return False
    details = getattr(error, "details", None) or {}
    if isinstance(details, dict) and details.get("governor"):
        return False
    if getattr(error, "category", None) == ErrorCategory.RATE_LIMIT:
        return True
    if getattr(error, "status_code", None) == 429 or getattr(result, "status_code", None) == 429:
        return True
    if isinstance(details, dict) and details.get("code") == 429:
        return True
    return "calm down, cowboy" in str(getattr(error, "message", "")).lower()


class EldoradoGovernor:
    """File-backed per-store budget. Safe across processes on one host."""

    def __init__(
        self,
        state_dir: Path | str | None = None,
        *,
        write_min_interval: float | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._dir = Path(state_dir) if state_dir else default_state_dir()
        self._interval = (
            write_min_interval
            if write_min_interval is not None
            else _env_float("ELDORADO_WRITE_MIN_INTERVAL_SECONDS", DEFAULT_WRITE_MIN_INTERVAL_SECONDS)
        )
        self._clock = clock
        self._sleep = sleep

    # -- state ---------------------------------------------------------------

    @contextlib.contextmanager
    def _state(self, store: str) -> Iterator[dict[str, Any]]:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{store_key(store)}.json"
        with open(path, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                handle.seek(0)
                raw = handle.read()
                try:
                    state = json.loads(raw) if raw.strip() else {}
                except ValueError:
                    state = {}
                yield state
                handle.seek(0)
                handle.truncate()
                handle.write(json.dumps(state, sort_keys=True))
                handle.flush()
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _count(self, state: dict[str, Any], field: str, now: float) -> None:
        hour = time.strftime("%Y-%m-%dT%H", time.gmtime(now))
        hours = state.setdefault("hours", {})
        bucket = hours.setdefault(hour, {})
        bucket[field] = int(bucket.get(field, 0)) + 1
        if len(hours) > HOURS_KEPT:
            for old in sorted(hours)[: len(hours) - HOURS_KEPT]:
                hours.pop(old, None)

    # -- admission -------------------------------------------------------------

    def write_cooldown_remaining(self, store: str) -> float:
        with self._state(store) as state:
            return max(0.0, float(state.get("write_cooldown_until", 0)) - self._clock())

    def seconds_until_write(self, store: str) -> float:
        """0 when a write could start now; otherwise how long until it could."""
        with self._state(store) as state:
            now = self._clock()
            return max(
                0.0,
                float(state.get("write_cooldown_until", 0)) - now,
                float(state.get("next_write_at", 0)) - now,
            )

    def acquire_write(self, store: str, *, max_wait: float) -> tuple[bool, str, float]:
        """Reserve this store's next write slot, waiting up to ``max_wait`` seconds.

        Returns ``(admitted, reason, retry_after_seconds)``.
        """
        waited = 0.0
        while True:
            with self._state(store) as state:
                now = self._clock()
                cooldown = float(state.get("write_cooldown_until", 0)) - now
                if cooldown > 0:
                    self._count(state, "refused_cooldown", now)
                    return False, "cowboy_cooldown", cooldown
                wait = float(state.get("next_write_at", 0)) - now
                if wait <= 0:
                    state["next_write_at"] = now + self._interval
                    self._count(state, "write", now)
                    return True, "", 0.0
                if waited + wait > max_wait:
                    self._count(state, "refused_budget", now)
                    return False, "write_budget", wait
            self._sleep(wait)
            waited += wait

    def admit_read(self, store: str) -> tuple[bool, float]:
        with self._state(store) as state:
            now = self._clock()
            cooldown = float(state.get("read_cooldown_until", 0)) - now
            if cooldown > 0:
                self._count(state, "refused_read_cooldown", now)
                return False, cooldown
            self._count(state, "read", now)
            return True, 0.0

    # -- outcomes --------------------------------------------------------------

    def record_write_result(self, store: str, result: Any) -> float:
        """Apply the cowboy ladder; returns the pause opened (0 when none)."""
        with self._state(store) as state:
            now = self._clock()
            if is_rate_limited(result):
                self._count(state, "write_429", now)
                consecutive = int(state.get("consecutive_429", 0)) + 1
                state["consecutive_429"] = consecutive
                if consecutive >= COWBOY_CIRCUIT_THRESHOLD:
                    pause = COWBOY_CIRCUIT_SECONDS
                else:
                    pause = COWBOY_BACKOFF_SECONDS[min(consecutive, len(COWBOY_BACKOFF_SECONDS)) - 1]
                retry_after = getattr(getattr(result, "error", None), "retry_after", None) or 0
                pause = max(pause, float(retry_after))
                state["write_cooldown_until"] = max(float(state.get("write_cooldown_until", 0)), now + pause)
                return pause
            if getattr(result, "ok", False):
                state["consecutive_429"] = 0
            return 0.0

    def record_read_result(self, store: str, result: Any) -> None:
        if not is_rate_limited(result):
            return
        with self._state(store) as state:
            now = self._clock()
            self._count(state, "read_429", now)
            retry_after = getattr(getattr(result, "error", None), "retry_after", None) or 0
            state["read_cooldown_until"] = max(
                float(state.get("read_cooldown_until", 0)),
                now + max(READ_COOLDOWN_SECONDS, float(retry_after)),
            )

    # -- reporting -------------------------------------------------------------

    def snapshot(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        if not self._dir.exists():
            return out
        for path in sorted(self._dir.glob("*.json")):
            with self._state(path.stem) as state:
                out[path.stem] = json.loads(json.dumps(state))
        return out


def _refused(reason: str, retry_after: float, store: str) -> ApiResult[Any]:
    return ApiResult.from_error(
        ErrorCategory.RATE_LIMIT,
        f"ELDORADO_GOVERNOR_{reason.upper()}: {store} paused for {int(retry_after)}s (no request sent)",
        provider="eldorado",
        retry_after=retry_after,
        is_retryable=True,
        details={"governor": reason, "store": store},
    )


def is_governor_refusal(result: Any) -> bool:
    details = getattr(getattr(result, "error", None), "details", None) or {}
    return isinstance(details, dict) and bool(details.get("governor"))


class GovernedEldoradoFacade:
    """Wraps an ``EldoradoFacade`` so every call obeys the store's governor."""

    def __init__(
        self,
        inner: Any,
        store: str,
        *,
        governor: EldoradoGovernor | None = None,
        max_write_wait: float | None = None,
    ) -> None:
        self._inner = inner
        self.governor_store = store_key(store)
        self.governor = governor or EldoradoGovernor()
        self._max_write_wait = (
            max_write_wait
            if max_write_wait is not None
            else _env_float("ELDORADO_MAX_WRITE_WAIT_SECONDS", DEFAULT_MAX_WRITE_WAIT_SECONDS)
        )

    def write_cooldown_remaining(self) -> float:
        return self.governor.write_cooldown_remaining(self.governor_store)

    def seconds_until_write(self) -> float:
        return self.governor.seconds_until_write(self.governor_store)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not callable(attr) or name.startswith("_"):
            return attr
        store = self.governor_store
        governor = self.governor

        if name in WRITE_METHODS:
            def governed_write(*args: Any, **kwargs: Any) -> Any:
                admitted, reason, retry_after = governor.acquire_write(store, max_wait=self._max_write_wait)
                if not admitted:
                    return _refused(reason, retry_after, store)
                result = attr(*args, **kwargs)
                governor.record_write_result(store, result)
                return result
            return governed_write

        def governed_read(*args: Any, **kwargs: Any) -> Any:
            admitted, retry_after = governor.admit_read(store)
            if not admitted:
                return _refused("read_cooldown", retry_after, store)
            result = attr(*args, **kwargs)
            governor.record_read_result(store, result)
            return result
        return governed_read
