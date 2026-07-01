"""Cloudflare cf_clearance cookie provider.

Uses DrissionPage (Chromium) to solve the Cloudflare JS challenge once,
then caches the resulting cf_clearance cookie for reuse across many
requests.  Re-solves automatically when the cookie expires or a 403 is
encountered.

On headless Linux servers (no DISPLAY), a virtual framebuffer (Xvfb) is
started automatically so the browser runs in non-headless mode — this is
required because Cloudflare detects and blocks HeadlessChrome.

Server setup (Ubuntu):
    apt-get install -y xvfb chromium-browser
    pip install DrissionPage PyVirtualDisplay
"""

from __future__ import annotations

import logging
import os
import platform
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Cloudflare challenge page titles (multi-language)
_CF_CHALLENGE_TITLES = frozenset({
    "just a moment",
    "bir dakika",  # Turkish
    "un momento",  # Spanish
    "einen moment",  # German
    "un instant",  # French
})

_DEFAULT_MAX_WAIT = 45  # seconds to wait for challenge resolution
_DEFAULT_TTL = 900  # 15 minutes — refresh before Cloudflare expires it


def _needs_virtual_display() -> bool:
    """Check if we need Xvfb (Linux without a display)."""
    if platform.system() != "Linux":
        return False
    return not os.environ.get("DISPLAY")


@dataclass
class CfCookieResult:
    """Resolved Cloudflare cookie set."""
    cf_clearance: str
    user_agent: str
    extra_cookies: dict[str, str] = field(default_factory=dict)
    obtained_at: float = field(default_factory=time.time)
    ttl: float = _DEFAULT_TTL

    @property
    def is_expired(self) -> bool:
        return time.time() - self.obtained_at > self.ttl

    def to_cookie_header(self) -> str:
        """Build Cookie header value."""
        parts = [f"cf_clearance={self.cf_clearance}"]
        for name, value in self.extra_cookies.items():
            parts.append(f"{name}={value}")
        return "; ".join(parts)


class CfCookieProvider:
    """Manages cf_clearance cookies via browser-based challenge solving.

    Thread-safe — only one browser session runs at a time.
    Multiple callers waiting for a cookie will share the same result.

    On Linux servers without a display, automatically starts Xvfb so the
    browser can run in non-headless mode (Cloudflare blocks HeadlessChrome).

    Usage:
        provider = CfCookieProvider("https://r6skins.locker")
        cookies = provider.get_cookies()  # solves challenge on first call
        # ... use cookies.cf_clearance in requests ...
        provider.invalidate()  # force re-solve on next call
    """

    def __init__(
        self,
        base_url: str,
        *,
        warmup_path: str = "/",
        ttl: float = _DEFAULT_TTL,
        max_wait: int = _DEFAULT_MAX_WAIT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._warmup_path = warmup_path
        self._ttl = ttl
        self._max_wait = max_wait
        self._cached: CfCookieResult | None = None
        self._lock = threading.Lock()

    def get_cookies(self) -> CfCookieResult | None:
        """Get valid cf_clearance cookies, solving challenge if needed.

        Returns None if the challenge cannot be solved.
        """
        # Fast path — cache hit
        if self._cached and not self._cached.is_expired:
            return self._cached

        with self._lock:
            # Double-check after acquiring lock
            if self._cached and not self._cached.is_expired:
                return self._cached
            return self._solve()

    def invalidate(self) -> None:
        """Force re-solve on next get_cookies() call."""
        self._cached = None

    def _solve(self) -> CfCookieResult | None:
        """Open browser, solve Cloudflare challenge, extract cookies."""
        try:
            from DrissionPage import ChromiumPage, ChromiumOptions
        except ImportError:
            logger.error(
                "DrissionPage is not installed. "
                "Install it with: pip install DrissionPage"
            )
            return None

        vdisplay = None
        page = None
        try:
            # On Linux without display: start virtual framebuffer
            if _needs_virtual_display():
                vdisplay = self._start_virtual_display()
                if vdisplay is None:
                    return None

            co = ChromiumOptions()
            # Always non-headless — Cloudflare detects HeadlessChrome.
            # On servers, Xvfb provides the virtual display.
            co.set_argument('--no-sandbox')
            co.set_argument('--disable-gpu')
            co.set_argument('--disable-blink-features=AutomationControlled')
            co.set_argument('--window-size=1920,1080')

            page = ChromiumPage(co)
            warmup_url = f"{self._base_url}{self._warmup_path}"
            logger.info("CfCookieProvider: navigating to %s", warmup_url)

            page.get(warmup_url)

            # Wait for challenge to resolve
            resolved = False
            for i in range(self._max_wait):
                title = (page.title or "").lower()
                if not any(challenge in title for challenge in _CF_CHALLENGE_TITLES):
                    resolved = True
                    break
                time.sleep(1)

            if not resolved:
                logger.warning(
                    "CfCookieProvider: challenge not resolved after %ds (title: %s)",
                    self._max_wait, page.title,
                )
                return None

            # Extract cookies and user-agent
            user_agent = page.run_js("return navigator.userAgent") or ""
            raw_cookies = page.cookies()
            cookie_dict: dict[str, str] = {}
            for c in raw_cookies:
                name = c.get('name', '')
                value = c.get('value', '')
                if name and value:
                    cookie_dict[name] = value

            cf_clearance = cookie_dict.pop('cf_clearance', '')
            if not cf_clearance:
                logger.warning("CfCookieProvider: no cf_clearance cookie found")
                return None

            result = CfCookieResult(
                cf_clearance=cf_clearance,
                user_agent=user_agent,
                extra_cookies=cookie_dict,
                ttl=self._ttl,
            )
            self._cached = result
            logger.info(
                "CfCookieProvider: cf_clearance obtained (expires in %ds)",
                self._ttl,
            )
            return result

        except Exception:
            logger.exception("CfCookieProvider: failed to solve challenge")
            return None
        finally:
            if page is not None:
                try:
                    page.quit()
                except Exception:
                    pass
            if vdisplay is not None:
                try:
                    vdisplay.stop()
                except Exception:
                    pass

    @staticmethod
    def _start_virtual_display() -> Any | None:
        """Start Xvfb virtual display for headless Linux servers."""
        try:
            from pyvirtualdisplay import Display
        except ImportError:
            logger.error(
                "PyVirtualDisplay is not installed. "
                "Install it with: pip install PyVirtualDisplay\n"
                "Also ensure Xvfb is installed: apt-get install -y xvfb"
            )
            return None

        try:
            vdisplay = Display(visible=False, size=(1920, 1080))
            vdisplay.start()
            logger.info("CfCookieProvider: Xvfb virtual display started")
            return vdisplay
        except Exception:
            logger.exception("CfCookieProvider: failed to start Xvfb")
            return None
