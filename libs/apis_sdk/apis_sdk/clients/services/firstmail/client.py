"""
Low-level FirstMail API client.

Handles raw HTTP communication with the FirstMail API.
Returns ApiResult with parsed response models.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.exceptions import TransportError
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.clients.services.firstmail.config import FirstMailConfig
from apis_sdk.clients.services.firstmail.endpoints import FirstMailEndpoints
from apis_sdk.clients.services.firstmail.models import (
    ChangePasswordResponse,
    ChangePasswordStatus,
)


class FirstMailClient:
    """
    Low-level FirstMail API client.

    Handles:
    - Authentication (X-API-KEY header)
    - Request execution via injected transport
    - Response parsing into FirstMail-specific models
    - Error categorization (status code → ChangePasswordStatus)

    Does NOT handle:
    - Retry logic (caller's responsibility)
    - Password generation (that's the service layer's job)
    - DB persistence (that's the Django layer's job)
    """

    PROVIDER = "firstmail"

    def __init__(
        self,
        config: FirstMailConfig,
        transport: BaseHttpTransport,
        *,
        logger: SdkLogger | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._logger = logger or NullLogger()

    def _build_url(self, path: str) -> str:
        return f"{self._config.base_url}{path}"

    def _auth_headers(self) -> dict[str, str]:
        return {
            "X-API-KEY": self._config.api_key,
            "Content-Type": "application/json",
        }

    def change_password(
        self,
        email: str,
        current_password: str,
        new_password: str,
        *,
        proxy_url: str | None = None,
    ) -> ApiResult[ChangePasswordResponse]:
        """
        Change an email account password via FirstMail API.

        Args:
            email: The email address to change password for.
            current_password: Current password of the account.
            new_password: Desired new password.
            proxy_url: Optional proxy URL for this request.

        Returns:
            ApiResult containing ChangePasswordResponse.
            Rate limit (403) is returned as a retryable error (NOT auto-retried here).
        """
        url = self._build_url(FirstMailEndpoints.CHANGE_PASSWORD)
        payload = {
            "email": email,
            "current_password": current_password,
            "new_password": new_password,
        }

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                headers=self._auth_headers(),
                json_body=payload,
                timeout=self._config.timeout,
                proxy_url=proxy_url,
            )
        except TransportError as exc:
            self._logger.error("FirstMail API request failed", error=str(exc), email=email)
            return ApiResult.from_error(
                ErrorCategory.NETWORK,
                str(exc),
                provider=self.PROVIDER,
                is_retryable=True,
            )

        return self._parse_response(response, email)

    def _parse_response(
        self, response: Any, email: str
    ) -> ApiResult[ChangePasswordResponse]:
        """Map HTTP response to typed ChangePasswordResponse."""
        status_code = response.status_code

        try:
            data = response.json() if response.text else {}
        except Exception:
            data = {}

        # 200 — success
        if status_code == 200 and data.get("success"):
            result = ChangePasswordResponse(
                status=ChangePasswordStatus.SUCCESS,
                success=True,
                email=email,
                http_status=status_code,
            )
            self._logger.info("Password changed successfully", email=email)
            return ApiResult.success(result, status_code=status_code)

        # 401 — wrong password
        if status_code == 401:
            result = ChangePasswordResponse(
                status=ChangePasswordStatus.WRONG_PASSWORD,
                success=False,
                email=email,
                http_status=status_code,
                error_message="Wrong password",
            )
            return ApiResult.success(result, status_code=status_code)

        # 404 — email not found
        if status_code == 404:
            result = ChangePasswordResponse(
                status=ChangePasswordStatus.NOT_FOUND,
                success=False,
                email=email,
                http_status=status_code,
                error_message="Email not found",
            )
            return ApiResult.success(result, status_code=status_code)

        # 400 — validation error (2FA, missing fields, etc.)
        if status_code == 400:
            error_msg = data.get("error", "Validation error")
            result = ChangePasswordResponse(
                status=ChangePasswordStatus.VALIDATION_ERROR,
                success=False,
                email=email,
                http_status=status_code,
                error_message=error_msg,
            )
            return ApiResult.success(result, status_code=status_code)

        # 403 — rate limit OR forbidden
        if status_code == 403:
            body_text = response.text if hasattr(response, "text") else ""
            if "rate limit" in body_text.lower():
                self._logger.warning("Rate limited by FirstMail", email=email)
                return ApiResult.from_error(
                    ErrorCategory.RATE_LIMIT,
                    "API rate limit reached",
                    status_code=status_code,
                    provider=self.PROVIDER,
                    is_retryable=True,
                    retry_after=30.0,
                )
            # Non-rate-limit 403
            error_msg = data.get("error", "Forbidden")
            result = ChangePasswordResponse(
                status=ChangePasswordStatus.FORBIDDEN,
                success=False,
                email=email,
                http_status=status_code,
                error_message=error_msg,
            )
            return ApiResult.success(result, status_code=status_code)

        # 500 — server error
        if status_code == 500:
            result = ChangePasswordResponse(
                status=ChangePasswordStatus.SERVER_ERROR,
                success=False,
                email=email,
                http_status=status_code,
                error_message="Internal server error",
            )
            return ApiResult.success(result, status_code=status_code)

        # Unknown status
        error_msg = data.get("error", f"HTTP {status_code}")
        result = ChangePasswordResponse(
            status=ChangePasswordStatus.UNKNOWN,
            success=False,
            email=email,
            http_status=status_code,
            error_message=error_msg,
        )
        return ApiResult.success(result, status_code=status_code)
