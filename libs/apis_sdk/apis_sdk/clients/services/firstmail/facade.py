"""
FirstMail high-level facade.

Provides a clean, consumer-facing API that combines:
- The low-level FirstMailClient (API calls)
- Optional retry policy (rate limit handling)
- Error normalization

This is the primary entry point for consumers using FirstMail.
"""

from __future__ import annotations

from typing import Callable, Protocol, TypeVar

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.exceptions import ProviderError, RateLimitError, TransportError
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.infrastructure.retry.policy import RetryPolicy
from apis_sdk.clients.services.firstmail.config import FirstMailConfig
from apis_sdk.clients.services.firstmail.models import ChangePasswordResponse

T = TypeVar("T")


class FirstMailApiClient(Protocol):
    def change_password(
        self,
        email: str,
        current_password: str,
        new_password: str,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[ChangePasswordResponse]: ...


class FirstMailFacade:
    """
    High-level interface for the FirstMail email service.

    Usage:
        facade = FirstMailFacade(client=firstmail_client)
        result = facade.change_password("user@mail.com", "old", "new")
        if result.ok and result.data.success:
            print("Password changed!")
    """

    def __init__(
        self,
        client: FirstMailApiClient,
        *,
        config: FirstMailConfig | None = None,
        retry_policy: RetryPolicy | None = None,
        max_retry_attempts: int = 3,
        logger: SdkLogger | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._retry = retry_policy
        self._max_retry_attempts = max(1, max_retry_attempts)
        self._logger = logger or NullLogger()

    @property
    def provider_name(self) -> str:
        return "firstmail"

    def change_password(
        self,
        email: str,
        current_password: str,
        new_password: str,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[ChangePasswordResponse]:
        """
        Change an email account password.

        Handles retry on rate limit (403) if a retry policy is configured.

        Args:
            email: Email address.
            current_password: Current password.
            new_password: New password.
            proxy_url: Optional proxy URL.

        Returns:
            ApiResult[ChangePasswordResponse]
        """

        def operation() -> ApiResult[ChangePasswordResponse]:
            return self._client.change_password(
                email, current_password, new_password, proxy_url=proxy_url,
            )

        return self._execute_with_retry(operation)

    def _execute_with_retry(
        self, operation: Callable[[], ApiResult[T]]
    ) -> ApiResult[T]:
        """Execute an operation with optional retry policy."""
        if self._retry is None:
            return operation()

        def wrapped() -> ApiResult[T]:
            result = operation()
            if result.ok:
                return result
            error = result.error
            if error is not None:
                if error.category == ErrorCategory.RATE_LIMIT:
                    raise RateLimitError(
                        error.message,
                        provider="firstmail",
                        retry_after=error.retry_after,
                    )
                if error.category == ErrorCategory.NETWORK:
                    raise TransportError(error.message, provider="firstmail")
                raise ProviderError(
                    error.message,
                    provider="firstmail",
                    status_code=error.status_code,
                    is_retryable=error.is_retryable,
                )
            raise ProviderError(
                "FirstMail operation failed without error details.",
                provider="firstmail",
                is_retryable=False,
            )

        try:
            return self._retry.execute(wrapped, max_attempts=self._max_retry_attempts)
        except Exception as exc:
            self._logger.warning("FirstMail operation exhausted retries", error=str(exc))
            return ApiResult.from_error(
                ErrorCategory.SERVER_ERROR,
                str(exc),
                provider="firstmail",
                is_retryable=False,
            )
