"""Cloudflare cf_clearance cookie provider (nodriver + residential relay).

Solves the Cloudflare "Verify you are human" (Turnstile) challenge with a REAL
Chrome driven by nodriver under a virtual display (Xvfb :99), through a sticky
residential proxy, then caches the resulting cf_clearance + connect.sid cookies
for reuse across many curl requests.

Proven facts (2026-07-03) this design relies on:
  * cf_clearance is bound to the EXIT IP, not primarily to the TLS/JA3
    fingerprint — so the browser (solve) and the curl transport (fetch) MUST
    use the SAME sticky exit IP. The cookie is therefore paired with the exact
    proxy_url it was minted on (see CfCookieResult.proxy_url).
  * cf_clearance is domain-wide, so one cookie set serves many accounts.
  * curl_cffi impersonate=chrome124 transfers the cookie fine on the same IP.

Design:
  * Each solve runs in a FRESH subprocess — nodriver hangs on a repeated
    uc.start() in the same process, and this keeps the long-lived parent
    (Django/Celery) free of nodriver's event loop entirely.
  * Single-flight: a threading.Lock + double-check means concurrent callers
    share ONE browser solve; a second Chrome never opens.
  * Rotation: the exit IP is rotated (new cf_clearance minted) either
    reactively (invalidate/rotate on 403/429, driven by the facade) or
    proactively after a jittered request budget or a soft age cap.

Server deps: Xvfb (:99), real google-chrome, `pip install nodriver opencv-python`.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import multiprocessing
import os
import random
import tempfile
import threading
import time
from dataclasses import dataclass, field

from apis_sdk.infrastructure.proxy.sticky import StickyResidentialProxy

logger = logging.getLogger(__name__)

# Cloudflare challenge page titles (multi-language) — while the title matches
# one of these, the page has NOT resolved yet.
_CF_CHALLENGE_TITLES = frozenset({
    "just a moment",
    "bir dakika",       # Turkish
    "un momento",       # Spanish
    "einen moment",     # German
    "un instant",       # French
})

_DEFAULT_CHROME = "/usr/bin/google-chrome"
_DEFAULT_DISPLAY = ":99"

_DEFAULT_SOLVE_ATTEMPTS = 3        # whole-solve retries (each a fresh process)
_DEFAULT_CLICK_ATTEMPTS = 4        # Turnstile clicks within one browser
_DEFAULT_WAIT_AFTER_CLICK = 8      # seconds to wait for cf_clearance after a click
_DEFAULT_SOLVE_TIMEOUT = 90        # per-attempt subprocess hard timeout (s)

_DEFAULT_BUDGET = 50               # requests per identity before proactive rotate
_DEFAULT_BUDGET_JITTER = 10        # +/- jitter so rotation isn't a fixed number
_DEFAULT_MAX_AGE = 1800            # soft age cap (s) — rotate even if under budget


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class CfCookieResult:
    """Resolved Cloudflare cookie set, paired with the exit IP it is valid on."""

    cf_clearance: str
    user_agent: str
    proxy_url: str                                   # the exit IP curl MUST reuse
    extra_cookies: dict[str, str] = field(default_factory=dict)  # e.g. connect.sid
    obtained_at: float = field(default_factory=time.time)

    @property
    def age(self) -> float:
        return time.time() - self.obtained_at

    def to_cookie_header(self) -> str:
        """Build a Cookie header value (cf_clearance + any extra cookies)."""
        parts = [f"cf_clearance={self.cf_clearance}"]
        for name, value in self.extra_cookies.items():
            parts.append(f"{name}={value}")
        return "; ".join(parts)


# ---------------------------------------------------------------------------
# Browser solve — runs in a FRESH subprocess (module-level for spawn pickling)
# ---------------------------------------------------------------------------

def _solve_worker(params: dict, queue) -> None:
    """Subprocess entry point: open Chrome, solve Cloudflare, return cookies.

    Puts a dict {cf_clearance, extra, user_agent} on the queue on success,
    None on a clean failure, or {"__error__": repr} on an exception.
    """
    try:
        # Isolate verify_cf's temp files (screen.jpg / cf_template.png land in CWD).
        os.chdir(tempfile.mkdtemp(prefix="cf_solve_"))
        os.environ.setdefault("DISPLAY", params.get("display") or _DEFAULT_DISPLAY)
        import nodriver as uc  # noqa: PLC0415 — heavy; keep out of parent import

        data = uc.loop().run_until_complete(_async_browser_solve(params))
        queue.put(data)
    except Exception as exc:  # noqa: BLE001
        queue.put({"__error__": repr(exc)})


async def _async_browser_solve(params: dict) -> dict | None:
    import nodriver as uc  # noqa: PLC0415
    from apis_sdk.infrastructure.proxy.relay import LocalProxyRelay  # noqa: PLC0415

    relay = LocalProxyRelay(
        params["up_host"], params["up_port"], params["auth_b64"]
    )
    relay_url = await relay.start()

    browser = await uc.start(
        headless=False,  # Cloudflare blocks HeadlessChrome; Xvfb provides the display.
        browser_executable_path=params["chrome"],
        browser_args=[
            "--no-sandbox",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
            "--window-size=1280,720",
            f"--proxy-server={relay_url}",
        ],
    )
    try:
        page = await browser.get(params["solve_url"])
        if not await _turnstile_solve(page, params):
            return None

        try:
            user_agent = await page.evaluate("navigator.userAgent") or ""
        except Exception:  # noqa: BLE001
            user_agent = ""

        cookies: dict[str, str] = {}
        try:
            for c in await browser.cookies.get_all():
                if c.name in ("cf_clearance", "connect.sid"):
                    cookies[c.name] = c.value
        except Exception:  # noqa: BLE001
            pass

        cf_clearance = cookies.pop("cf_clearance", "")
        if not cf_clearance:
            return None
        return {
            "cf_clearance": cf_clearance,
            "extra": cookies,               # connect.sid etc.
            "user_agent": str(user_agent),
        }
    finally:
        try:
            browser.stop()
        except Exception:  # noqa: BLE001
            pass
        await relay.stop()


async def _turnstile_solve(page, params: dict) -> bool:
    """Click the Turnstile checkbox until the page resolves (or give up)."""
    attempts = int(params["click_attempts"])
    wait = int(params["wait_after_click"])
    for _ in range(attempts):
        if await _is_loaded(page):
            return True
        title = await _page_title(page)
        if not any(t in title.lower() for t in _CF_CHALLENGE_TITLES):
            return True  # no challenge present
        try:
            # nodriver locates the checkbox via OpenCV template match (needs cv2).
            await page.verify_cf(flash=False)
        except Exception:  # noqa: BLE001
            pass
        for _ in range(wait):
            await asyncio.sleep(1)
            if await _is_loaded(page):
                return True
    return await _is_loaded(page)


async def _page_title(page) -> str:
    try:
        return str(await page.evaluate("document.title") or "")
    except Exception:  # noqa: BLE001
        return ""


async def _is_loaded(page) -> bool:
    """True once the CF challenge is gone, the DOM is ready and has content."""
    title = await _page_title(page)
    if any(t in title.lower() for t in _CF_CHALLENGE_TITLES):
        return False
    try:
        ready = await page.evaluate("document.readyState")
    except Exception:  # noqa: BLE001
        ready = ""
    if ready != "complete":
        return False
    try:
        body_len = await page.evaluate(
            "document.body ? document.body.innerText.length : 0"
        )
    except Exception:  # noqa: BLE001
        body_len = 0
    return bool(title) and int(body_len or 0) > 50


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class CfCookieProvider:
    """Manages cf_clearance cookies via nodriver-based challenge solving.

    Thread-safe single-flight: concurrent callers share one browser solve.
    The cookie is paired with the sticky exit IP it was minted on; the facade
    must route its curl request through :attr:`CfCookieResult.proxy_url`.

    Usage:
        proxy = StickyResidentialProxy.from_record(db_proxy_record)
        provider = CfCookieProvider(proxy, solve_url="https://r6skins.locker/profile/<seed>")
        cookies = provider.get_cookies()      # solves on first call
        provider.note_use()                   # count one request (budget)
        provider.invalidate()                 # 403: re-solve on SAME IP
        provider.rotate()                     # ban/429: NEW IP + re-solve
    """

    def __init__(
        self,
        proxy: StickyResidentialProxy,
        *,
        solve_url: str | None = None,
        chrome_path: str = _DEFAULT_CHROME,
        display: str = _DEFAULT_DISPLAY,
        solve_attempts: int = _DEFAULT_SOLVE_ATTEMPTS,
        click_attempts: int = _DEFAULT_CLICK_ATTEMPTS,
        wait_after_click: int = _DEFAULT_WAIT_AFTER_CLICK,
        solve_timeout: float = _DEFAULT_SOLVE_TIMEOUT,
        budget: int = _DEFAULT_BUDGET,
        budget_jitter: int = _DEFAULT_BUDGET_JITTER,
        max_age: float = _DEFAULT_MAX_AGE,
    ) -> None:
        self._proxy = proxy
        self._solve_url = solve_url
        self._chrome_path = chrome_path
        self._display = display
        self._solve_attempts = max(1, solve_attempts)
        self._click_attempts = click_attempts
        self._wait_after_click = wait_after_click
        self._solve_timeout = solve_timeout
        self._budget_base = budget
        self._budget_jitter = budget_jitter
        self._max_age = max_age

        self._lock = threading.Lock()
        self._cached: CfCookieResult | None = None
        self._use_count = 0
        self._budget = self._jittered_budget()
        self._force_solve = False   # re-solve on SAME IP (invalidate)
        self._force_rotate = False  # NEW IP + re-solve (rotate)

    # -- public API ---------------------------------------------------------

    def get_cookies(self, solve_url: str | None = None) -> CfCookieResult | None:
        """Return valid cookies, solving/rotating if needed. None on failure.

        ``solve_url`` is the profile page to solve the challenge on if a solve
        is triggered. In the posting flow this is the profile of the account
        currently being fetched — cf_clearance is domain-wide, so any real
        profile works and there is no fixed "seed" profile to maintain. The
        most recently supplied value is remembered as the solve target.
        """
        if solve_url:
            self._solve_url = solve_url
        cached = self._cached
        if cached is not None and not self._needs_refresh():
            return cached
        with self._lock:
            if self._cached is not None and not self._needs_refresh():
                return self._cached
            return self._resolve_locked()

    def note_use(self) -> None:
        """Record that the current cookie served one request (budget counter)."""
        with self._lock:
            self._use_count += 1

    def invalidate(self) -> None:
        """Force a re-solve on the SAME exit IP (e.g. cookie expired -> 403)."""
        with self._lock:
            self._cached = None
            self._force_solve = True

    def rotate(self) -> None:
        """Force a NEW exit IP + re-solve (e.g. IP banned / persistent 429)."""
        with self._lock:
            self._cached = None
            self._force_rotate = True

    # -- refresh policy -----------------------------------------------------

    def _needs_refresh(self) -> bool:
        if self._force_solve or self._force_rotate:
            return True
        cached = self._cached
        if cached is None:
            return True
        if cached.age >= self._max_age:
            return True
        if self._use_count >= self._budget:
            return True
        return False

    def _resolve_locked(self) -> CfCookieResult | None:
        # Proactive rotate: budget spent or too old. Reactive rotate: rotate flag.
        rotate = (
            self._force_rotate
            or self._use_count >= self._budget
            or (self._cached is not None and self._cached.age >= self._max_age)
        )
        if rotate:
            old = self._proxy.sessid
            new = self._proxy.rotate()
            logger.info("CfCookieProvider: rotating exit IP %s -> %s", old, new)

        result = self._spawn_solve()
        self._force_solve = False
        self._force_rotate = False
        if result is None:
            self._cached = None
            return None

        self._cached = result
        self._use_count = 0
        self._budget = self._jittered_budget()
        return result

    def _jittered_budget(self) -> int:
        lo = max(1, self._budget_base - self._budget_jitter)
        hi = self._budget_base + self._budget_jitter
        return random.randint(lo, hi)

    # -- solving ------------------------------------------------------------

    def _spawn_solve(self) -> CfCookieResult | None:
        """Solve in fresh subprocesses; rotate IP between failed attempts."""
        if not self._solve_url:
            logger.warning("CfCookieProvider: no solve_url set — cannot solve")
            return None
        for attempt in range(1, self._solve_attempts + 1):
            logger.info(
                "CfCookieProvider: solve attempt %d/%d (sessid=%s)",
                attempt, self._solve_attempts, self._proxy.sessid,
            )
            data = self._run_worker_once()
            if data:
                logger.info("CfCookieProvider: cf_clearance obtained")
                return CfCookieResult(
                    cf_clearance=data["cf_clearance"],
                    user_agent=data.get("user_agent", ""),
                    proxy_url=self._proxy.proxy_url,
                    extra_cookies=data.get("extra", {}),
                )
            # This IP couldn't pass — try a fresh IP on the next attempt.
            if attempt < self._solve_attempts:
                self._proxy.rotate()
        logger.warning("CfCookieProvider: all %d solve attempts failed",
                       self._solve_attempts)
        return None

    def _run_worker_once(self) -> dict | None:
        ctx = multiprocessing.get_context("spawn")
        queue = ctx.Queue()
        proc = ctx.Process(
            target=_solve_worker, args=(self._build_params(), queue), daemon=True
        )
        proc.start()
        data = None
        try:
            data = queue.get(timeout=self._solve_timeout)
        except Exception:  # noqa: BLE001 — Empty on timeout
            logger.warning("CfCookieProvider: solve worker timed out (%ss)",
                           self._solve_timeout)
        proc.join(timeout=5)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)
            if proc.is_alive():
                proc.kill()
        if isinstance(data, dict) and "__error__" in data:
            logger.warning("CfCookieProvider: solve worker error: %s",
                           data["__error__"])
            return None
        return data

    def _build_params(self) -> dict:
        auth = base64.b64encode(
            f"{self._proxy.username}:{self._proxy.password}".encode()
        ).decode()
        return {
            "up_host": self._proxy.host,
            "up_port": self._proxy.port,
            "auth_b64": auth,
            "solve_url": self._solve_url,
            "chrome": self._chrome_path,
            "display": self._display,
            "click_attempts": self._click_attempts,
            "wait_after_click": self._wait_after_click,
        }
