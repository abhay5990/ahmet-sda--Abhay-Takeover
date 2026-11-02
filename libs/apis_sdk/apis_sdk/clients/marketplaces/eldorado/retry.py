"""
Eldorado-specific retry strategy.

Overrides the marketplace family defaults where Eldorado's behavior
differs. For example, Eldorado rate limits are sometimes IP-based,
so 429 responses may benefit from proxy rotation + session reset.
"""

from __future__ import annotations

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.exceptions import (
    AuthenticationError,
    RateLimitError,
    TransportError,
)
from apis_sdk.infrastructure.retry.decision import RetryDecision
from apis_sdk.infrastructure.retry.strategy import MarketplaceRetryStrategy


class EldoradoRetryStrategy(MarketplaceRetryStrategy):
    """
    Eldorado provider retry strategy.

    Differences from base MarketplaceRetryStrategy:
    - 429 rate limit: escalate to new proxy + new session
      (Eldorado rate limits are partially IP-based)
    - Auth errors: refresh auth (inherited from marketplace)

    This strategy is injected into the facade's retry execution loop
    via on_before_retry(), which handles session/proxy runtime actions.
    """

    def __init__(
        self,
        *,
        retry_on_auth: bool = True,
        rotate_proxy_on_rate_limit: bool = True,
    ) -> None:
        super().__init__(retry_on_auth=retry_on_auth)
        self._rotate_proxy_on_rate_limit = rotate_proxy_on_rate_limit

    def decide(self, attempt: int, error: Exception) -> RetryDecision:
        # A transport failure that explicitly originated from the selected
        # proxy must not reuse the facade's sticky proxy on the next upload
        # attempt.  ``RuntimeRetryStrategy`` reports and excludes it before
        # acquiring a replacement, while the session reset clears any failed
        # connection state.
        if isinstance(error, TransportError) and error.details.get("proxy_url"):
            return RetryDecision.new_proxy_and_session(
                "Eldorado proxy transport failure, rotate proxy and reset session",
                error_category=ErrorCategory.NETWORK,
            )

        # Eldorado 429 ("Calm down, cowboy! Quota exceeded") is a per-SELLER-
        # ACCOUNT quota, not an IP limit: rotating proxies only sends more
        # requests into the same quota (2 Nov 2026: SDA retried every 429 and
        # kept both stores blocked). Never retry; the per-store governor
        # (governor.py) opens the 3/6/12/30-minute pause instead.
        if isinstance(error, RateLimitError):
            return RetryDecision.no_retry(
                "Eldorado per-account quota (429) — no retry; governor pauses this store",
                error_category=ErrorCategory.RATE_LIMIT,
            )

        # Everything else: delegate to marketplace family defaults
        return super().decide(attempt, error)
