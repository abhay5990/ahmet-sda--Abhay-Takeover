"""
Telegram Bot API client.

Minimal wrapper around the Telegram sendMessage endpoint.
Designed for system notifications (review alerts, error broadcasts, etc.).

Usage:
    from apis_sdk.clients.services.telegram.client import TelegramClient
    from apis_sdk.infrastructure.http.requests_transport import RequestsTransport

    client = TelegramClient(bot_token="...", transport=RequestsTransport())
    result = client.send_message(chat_id="-100xxx", text="Hello!")
    if not result.ok:
        logger.error("Telegram send failed: %s", result.error)
"""

from __future__ import annotations

from apis_sdk.core.enums import ErrorCategory, HttpMethod
from apis_sdk.core.result import ApiResult
from apis_sdk.infrastructure.http.base import BaseHttpTransport
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger

_BASE_URL = "https://api.telegram.org"
_TIMEOUT = 10.0


class TelegramClient:
    """
    Low-level Telegram Bot API client.

    Only implements sendMessage and getMe (connection test).
    The bot token is part of the URL path as required by the Bot API.
    """

    PROVIDER = "telegram"

    def __init__(
        self,
        bot_token: str,
        transport: BaseHttpTransport,
        *,
        logger: SdkLogger | None = None,
    ) -> None:
        self._token = bot_token
        self._transport = transport
        self._logger = logger or NullLogger()

    def send_message(
        self,
        *,
        chat_id: str,
        text: str,
        parse_mode: str | None = None,
    ) -> ApiResult[None]:
        """Send a text message to a Telegram chat.

        Args:
            chat_id: Target chat ID or @channel_username.
            text: Message text (max 4096 chars).
            parse_mode: Optional — "HTML" or "Markdown".

        Returns:
            ApiResult[None] — success has no data payload.
        """
        url = f"{_BASE_URL}/bot{self._token}/sendMessage"
        payload: dict = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            response = self._transport.request(
                HttpMethod.POST,
                url,
                json_body=payload,
                timeout=_TIMEOUT,
            )
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK,
                f"Telegram transport error: {exc}",
                provider=self.PROVIDER,
                is_retryable=True,
            )

        if not response.is_success:
            try:
                body = response.json()
                description = body.get("description", f"HTTP {response.status_code}")
            except Exception:
                description = f"HTTP {response.status_code}"

            category = (
                ErrorCategory.AUTHENTICATION
                if response.status_code in (401, 403)
                else ErrorCategory.SERVER_ERROR
            )
            return ApiResult.from_error(
                category,
                description,
                status_code=response.status_code,
                provider=self.PROVIDER,
                is_retryable=response.status_code >= 500,
            )

        return ApiResult.success(None, status_code=response.status_code)

    def get_me(self) -> ApiResult[dict]:
        """Call getMe to verify the bot token is valid.

        Returns:
            ApiResult[dict] — bot info on success.
        """
        url = f"{_BASE_URL}/bot{self._token}/getMe"
        try:
            response = self._transport.request(HttpMethod.GET, url, timeout=_TIMEOUT)
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK,
                f"Telegram getMe error: {exc}",
                provider=self.PROVIDER,
                is_retryable=True,
            )

        if not response.is_success:
            return ApiResult.from_error(
                ErrorCategory.AUTHENTICATION,
                f"Telegram token invalid: HTTP {response.status_code}",
                status_code=response.status_code,
                provider=self.PROVIDER,
            )

        try:
            body = response.json()
            return ApiResult.success(
                body.get("result", {}), status_code=response.status_code
            )
        except Exception as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                f"Telegram getMe parse error: {exc}",
                provider=self.PROVIDER,
            )
