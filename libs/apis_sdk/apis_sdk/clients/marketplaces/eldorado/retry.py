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
        # Eldorado-specific: 429 → rotate proxy + reset session
        if isinstance(error, RateLimitError) and self._rotate_proxy_on_rate_limit:
            return RetryDecision.new_proxy_and_session(
                "Eldorado rate limited, rotate proxy and reset session",
                delay_hint=error.retry_after,
                error_category=ErrorCategory.RATE_LIMIT,
            )

        # Everything else: delegate to marketplace family defaults
        return super().decide(attempt, error)
