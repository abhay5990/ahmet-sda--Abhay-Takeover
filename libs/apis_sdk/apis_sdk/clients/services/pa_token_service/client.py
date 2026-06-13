"""
Low-level PA Token Service client.

Communicates with the PA Token Service running on VDS that handles
PlayerAuctions browser-based authentication. The service manages
browser sessions and caching internally.

API:
    POST /authenticate  {username, password, proxy?}
    → {ok, success, token, authorization, cookie, duration, exitCode}

    GET /health
    → {ok, uptime, version}

All endpoints require X-API-Key header for authentication.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger

from .config import PaTokenServiceConfig
from .endpoints import PaTokenServiceEndpoints


@dataclass(frozen=True, slots=True)
class PaTokenResult:
    """Parsed result from PA Token Service authenticate endpoint."""

    access_token: str
    authorization: str
    cookie: str


class PaTokenServiceClient:
    """
    Low-level client for the PA Token Service microservice.

    Handles HTTP communication and response parsing.
    """

    PROVIDER = "pa_token_service"

    def __init__(
        self,
        config: PaTokenServiceConfig,
        transport: BaseHttpTransport,
        *,
        logger: SdkLogger | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._logger = logger or NullLogger()

    def authenticate(
        self,
        *,
        username: str,
        password: str,
        proxy: str | None = None,
    ) -> ApiResult[PaTokenResult]:
        """
        Request a fresh PA access token via Puppeteer login.

        Args:
            username: PlayerAuctions username.
            password: PlayerAuctions password.
            proxy: Optional proxy string (ip:port:user:pass format).

        Returns:
            ApiResult containing PaTokenResult on success.
        """
        url = f"{self._config.base_url}{PaTokenServiceEndpoints.AUTHENTICATE}"

        payload: dict[str, Any] = {
            "username": username,
            "password": password,
        }
        if proxy:
            payload["proxy"] = proxy

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                json_body=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": self._config.api_key,
                },
                timeout=self._config.timeout,
            )
        except Exception as exc:
            self._logger.warning(
                "PA Token Service transport error",
                error=str(exc),
            )
            return ApiResult.from_error(
                ErrorCategory.NETWORK,
                f"PA Token Service connection error: {exc}",
                provider=self.PROVIDER,
                is_retryable=True,
            )

        if not response.is_success:
            return ApiResult.from_error(
                ErrorCategory.SERVER_ERROR,
                f"PA Token Service HTTP {response.status_code}",
                status_code=response.status_code,
                provider=self.PROVIDER,
                is_retryable=response.status_code >= 500,
            )

        try:
            body = response.json()
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"PA Token Service invalid JSON: {exc}",
                provider=self.PROVIDER,
            )

        if not body.get("ok") or not body.get("success"):
            return ApiResult.from_error(
                ErrorCategory.AUTHENTICATION,
                f"PA Token Service login failed: exitCode={body.get('exitCode')}",
                provider=self.PROVIDER,
            )

        token = body.get("token", "")
        if not token:
            return ApiResult.from_error(
                ErrorCategory.AUTHENTICATION,
                "PA Token Service returned empty token",
                provider=self.PROVIDER,
            )

        result = PaTokenResult(
            access_token=token,
            authorization=body.get("authorization", f"Bearer {token}"),
            cookie=body.get("cookie", ""),
        )
        return ApiResult.success(result, status_code=response.status_code)

    def health_check(self) -> ApiResult[dict[str, Any]]:
        """Check if the microservice is running."""
        url = f"{self._config.base_url}{PaTokenServiceEndpoints.HEALTH}"
        try:
            response = self._transport.request(
                HttpMethod.GET,
                url,
                headers={"X-API-Key": self._config.api_key},
                timeout=5.0,
            )
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK,
                f"PA Token Service not reachable: {exc}",
                provider=self.PROVIDER,
            )

        if response.is_success:
            return ApiResult.success(response.json(), status_code=response.status_code)

        return ApiResult.from_error(
            ErrorCategory.SERVER_ERROR,
            f"PA Token Service unhealthy: HTTP {response.status_code}",
            provider=self.PROVIDER,
        )
