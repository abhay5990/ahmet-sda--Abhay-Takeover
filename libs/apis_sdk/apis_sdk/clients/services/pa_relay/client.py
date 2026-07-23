"""
PA Relay client.

Communicates with the PA Relay at http://35.231.166.148:3001 which proxies
all PlayerAuctions browser-based auth and offer posting.

Endpoints used:
    POST /warmup           — pre-fetch tokens into relay cache (call at startup)
    POST /pa-access-token  — get PA JWT (cache-first, instant if warmed up)
    POST /pa-post-offer    — post a new PA listing

All requests require X-Relay-Secret header.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger

from .config import PaRelayConfig

logger = logging.getLogger(__name__)

RELAY_SECRET_HEADER = "X-Relay-Secret"


@dataclass(frozen=True, slots=True)
class PaRelayTokenResult:
    """Parsed token result from /pa-access-token."""

    access_token: str
    cached: bool
    cookie: str = ""


class PaRelayClient:
    """
    Client for the PA Relay microservice.

    Replaces PaTokenServiceClient — uses the relay for all PA auth
    and offer posting instead of the old Puppeteer VDS.
    """

    PROVIDER = "pa_relay"

    def __init__(
        self,
        config: PaRelayConfig,
        transport: BaseHttpTransport,
        *,
        logger: SdkLogger | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._logger = logger or NullLogger()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_token(
        self,
        *,
        username: str,
        password: str,
        store: str,
    ) -> ApiResult[PaRelayTokenResult]:
        """
        Fetch a PA JWT from the relay (cache-first).

        Args:
            username: PA account email/username.
            password: PA account password.
            store:    Store slug, e.g. "ezsmurfmart" or "ezsmurfshop".

        Returns:
            ApiResult[PaRelayTokenResult] with access_token on success.
        """
        url = f"{self._config.base_url}/pa-access-token"
        payload: dict[str, Any] = {
            "username": username,
            "password": password,
            "store": store,
        }

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                json_body=payload,
                headers={
                    "Content-Type": "application/json",
                    RELAY_SECRET_HEADER: self._config.relay_secret,
                },
                timeout=self._config.token_timeout,
            )
        except Exception as exc:
            self._logger.warning(f"PA Relay /pa-access-token transport error: {exc}")
            return ApiResult.from_error(
                ErrorCategory.NETWORK,
                f"PA Relay connection error: {exc}",
                provider=self.PROVIDER,
                is_retryable=True,
            )

        if not response.is_success:
            return ApiResult.from_error(
                ErrorCategory.SERVER_ERROR,
                f"PA Relay HTTP {response.status_code}",
                status_code=response.status_code,
                provider=self.PROVIDER,
                is_retryable=response.status_code >= 500,
            )

        try:
            body = response.json()
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"PA Relay invalid JSON: {exc}",
                provider=self.PROVIDER,
            )

        if not body.get("ok"):
            return ApiResult.from_error(
                ErrorCategory.AUTHENTICATION,
                f"PA Relay token fetch failed: {body.get('error', 'unknown')}",
                provider=self.PROVIDER,
            )

        token = body.get("token", "")
        if not token:
            return ApiResult.from_error(
                ErrorCategory.AUTHENTICATION,
                "PA Relay returned empty token",
                provider=self.PROVIDER,
            )

        result = PaRelayTokenResult(
            access_token=token,
            cached=bool(body.get("cached", False)),
            cookie=str(body.get("cookie", "") or ""),
        )
        self._logger.info(f"PA Relay token fetched (cached={result.cached}, store={store})")
        return ApiResult.success(result, status_code=response.status_code)

    def warmup(
        self,
        stores: list[dict[str, str]],
        *,
        force_refresh: bool = False,
    ) -> bool:
        """
        Pre-fetch tokens into relay cache (call at startup).

        The relay /warmup endpoint accepts one store per request.
        This method fires one request per store and returns True if all succeed.

        Args:
            stores: List of {"store": slug, "username": email, "password": pw}
            force_refresh: If True, bypass cache and force new browser login.

        Returns:
            True if all warmup requests were accepted, False if any failed.
        """
        url = f"{self._config.base_url}/warmup"
        all_ok = True

        for store_entry in stores:
            payload: dict[str, Any] = {
                "store": store_entry.get("store", ""),
                "username": store_entry.get("username", ""),
                "password": store_entry.get("password", ""),
                "forceRefresh": force_refresh,
            }
            try:
                response = self._transport.request(
                    HttpMethod.POST,
                    url,
                    json_body=payload,
                    headers={
                        "Content-Type": "application/json",
                        RELAY_SECRET_HEADER: self._config.relay_secret,
                    },
                    timeout=10.0,  # Warmup responds instantly
                )
                if response.is_success:
                    self._logger.info(
                        f"PA Relay warmup accepted for store={store_entry.get('store')}"
                    )
                else:
                    self._logger.warning(
                        f"PA Relay warmup HTTP {response.status_code} for store={store_entry.get('store')}"
                    )
                    all_ok = False
            except Exception as exc:
                self._logger.warning(
                    f"PA Relay warmup error for store={store_entry.get('store')}: {exc}"
                )
                all_ok = False

        return all_ok

    def health_check(self) -> bool:
        """Quick liveness check — returns True if relay is reachable."""
        try:
            response = self._transport.request(
                HttpMethod.GET,
                f"{self._config.base_url}/disk-usage",
                headers={RELAY_SECRET_HEADER: self._config.relay_secret},
                timeout=5.0,
            )
            return response.is_success
        except Exception:
            return False
