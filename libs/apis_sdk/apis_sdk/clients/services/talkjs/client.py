"""
Low-level TalkJS API client.

TalkJS uses a non-standard API pattern:
- Chatbox/inbox endpoints return HTML with embedded JSON
- Query params are base64-encoded JSON blobs
- Auth is via bearer token (boken)

Because of this, we use requests directly rather than the SDK transport
abstraction (which assumes JSON responses).
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import requests

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.result import ApiResult
from apis_sdk.clients.services.talkjs.config import TalkJsConfig
from apis_sdk.clients.services.talkjs.endpoints import TalkJsEndpoints
from apis_sdk.clients.services.talkjs.html_parser import extract_json_from_html


class TalkJsClient:
    """
    Low-level TalkJS HTTP client.

    Handles:
    - Chatbox fetch (messages for a conversation)
    - Inbox fetch (conversation list)
    - Send message
    - Boken (auth token) retrieval

    All methods return ApiResult.
    """

    PROVIDER = "talkjs"

    def __init__(self, config: TalkJsConfig, *, token: str = "") -> None:
        self._config = config
        self._token = token
        self._session_id = str(uuid.uuid4())
        self._session = requests.Session()
        self._session.headers.update({
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        })

    @property
    def token(self) -> str:
        return self._token

    def set_token(self, token: str) -> None:
        """Update the bearer token (boken)."""
        self._token = token

    # ------------------------------------------------------------------
    # Boken (auth token)
    # ------------------------------------------------------------------

    def get_boken(self, signature: str) -> ApiResult[dict[str, Any]]:
        """Retrieve a TalkJS boken using a signature.

        Args:
            signature: TalkJS identity signature for the user.
        """
        url = TalkJsEndpoints.boken(self._config.app_id, self._config.user_id)
        params = {"signature": signature}
        headers = {
            "accept": "*/*",
            "content-type": "application/json",
            "origin": self._config.origin,
            "referer": self._config.referer,
        }

        try:
            resp = self._session.get(
                url, params=params, headers=headers,
                timeout=self._config.timeout,
            )
        except requests.RequestException as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not resp.ok:
            return self._http_error(resp)

        try:
            body = resp.json()
        except ValueError as exc:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN, f"Invalid JSON: {exc}",
                provider=self.PROVIDER,
            )

        boken = body.get("boken")
        if boken:
            self._token = boken

        return ApiResult.success(body, status_code=resp.status_code)

    # ------------------------------------------------------------------
    # Chatbox — fetch messages for a conversation
    # ------------------------------------------------------------------

    def fetch_chatbox(
        self,
        conversation_id: str,
        external_conv_id: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Fetch messages for a conversation via the chatbox HTML endpoint.

        Args:
            conversation_id: TalkJS internal conversation ID.
            external_conv_id: External conversation ID (UUID). Defaults to
                conversation_id if not provided.

        Returns:
            ApiResult containing parsed data with keys:
            - MESSAGES: {conv_id: {isComplete, dtos: {msg_id: {...}}}}
            - SIDES: conversation metadata
            - NYMS: user data
        """
        ext_id = external_conv_id or conversation_id
        url = TalkJsEndpoints.chatbox(
            self._config.app_id, self._config.user_id, conversation_id,
        )

        sync_please = {
            "me": {
                "__sync": False,
                "id": self._config.extern_id,
                "internalId": self._config.user_id,
            },
            "externalConversationId": ext_id,
        }

        local_settings = {
            "feedFilter": {},
            "messageFilter": {},
            "theme": {"name": "default_dark", "custom": {}},
            "view": {"timeZone": "UTC"},
        }

        params = {
            "syncPlease": self._b64json(sync_please),
            "localSettings": self._b64json(local_settings),
            "authToken": self._token,
            "clientHeight": "1216",
            "sessionId": self._session_id,
            "thirdparties": "",
            "id": self._config.extern_id,
        }

        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "referer": self._config.referer,
            "sec-fetch-dest": "iframe",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "cross-site",
        }

        try:
            resp = self._session.get(
                url, params=params, headers=headers,
                timeout=self._config.timeout,
            )
        except requests.RequestException as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not resp.ok:
            return self._http_error(resp)

        data = extract_json_from_html(resp.text)
        if data is None:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                "Could not extract JSON from chatbox HTML",
                provider=self.PROVIDER,
            )

        return ApiResult.success(data, status_code=resp.status_code)

    # ------------------------------------------------------------------
    # Inbox — fetch conversation list
    # ------------------------------------------------------------------

    def fetch_inbox(self) -> ApiResult[dict[str, Any]]:
        """Fetch inbox (conversation list) via HTML endpoint.

        Returns:
            ApiResult containing parsed data with keys:
            - SIDES: {user_id: {dtos: {conv_id: {...}}}}
            - MESSAGES: recent messages per conversation
            - NYMS: user data
        """
        url = TalkJsEndpoints.inbox(self._config.app_id, self._config.user_id)

        sync_please = {
            "me": {
                "__sync": False,
                "id": self._config.extern_id,
                "internalId": self._config.user_id,
            },
        }

        local_settings = {
            "feedFilter": {
                "custom": {
                    "hidden": ["!=", "true"],
                    "hiddenForUserId": ["!=", self._config.extern_id],
                },
            },
            "theme": {"name": "default_dark"},
            "view": {"timeZone": "UTC"},
        }

        params = {
            "syncPlease": self._b64json(sync_please),
            "localSettings": self._b64json(local_settings),
            "authToken": self._token,
            "clientHeight": "1216",
            "sessionId": self._session_id,
            "thirdparties": "",
            "id": self._config.extern_id,
        }

        headers = {
            "accept": "text/html",
            "origin": self._config.origin,
            "referer": self._config.referer,
        }

        try:
            resp = self._session.get(
                url, params=params, headers=headers,
                timeout=self._config.timeout,
            )
        except requests.RequestException as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not resp.ok:
            return self._http_error(resp)

        data = extract_json_from_html(resp.text)
        if data is None:
            return ApiResult.from_error(
                ErrorCategory.UNKNOWN,
                "Could not extract JSON from inbox HTML",
                provider=self.PROVIDER,
            )

        return ApiResult.success(data, status_code=resp.status_code)

    # ------------------------------------------------------------------
    # Send message
    # ------------------------------------------------------------------

    def send_message(
        self,
        conversation_id: str,
        text: str,
    ) -> ApiResult[dict[str, Any]]:
        """Send a text message to a conversation.

        Args:
            conversation_id: TalkJS conversation ID.
            text: Message body.
        """
        url = TalkJsEndpoints.say(self._config.app_id, conversation_id)

        headers = {
            "accept": "application/json",
            "authorization": f"bearer {self._token}",
            "content-type": "application/json",
            "origin": "https://app.talkjs.com",
            "referer": "https://app.talkjs.com/",
        }

        idempotency_key = "-" + base64.urlsafe_b64encode(
            uuid.uuid4().bytes,
        ).decode()[:19]

        payload = {
            "idempotencyKey": idempotency_key,
            "entityTree": [text],
            "received": False,
            "custom": {},
            "nymId": self._config.user_id,
            "attachment": None,
            "location": None,
        }

        params = {"sessionId": self._session_id}

        try:
            resp = self._session.post(
                url, json=payload, headers=headers, params=params,
                timeout=self._config.timeout,
            )
        except requests.RequestException as exc:
            return ApiResult.from_error(
                ErrorCategory.NETWORK, str(exc),
                provider=self.PROVIDER, is_retryable=True,
            )

        if not resp.ok:
            return self._http_error(resp)

        try:
            body = resp.json()
        except ValueError:
            body = {}

        return ApiResult.success(body, status_code=resp.status_code)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _b64json(obj: Any) -> str:
        """Base64-encode a JSON object for TalkJS query params."""
        return base64.b64encode(json.dumps(obj).encode()).decode()

    def _http_error(self, resp: requests.Response) -> ApiResult[Any]:
        category_map: dict[int, ErrorCategory] = {
            400: ErrorCategory.VALIDATION,
            401: ErrorCategory.AUTHENTICATION,
            403: ErrorCategory.AUTHENTICATION,
            404: ErrorCategory.NOT_FOUND,
            429: ErrorCategory.RATE_LIMIT,
        }
        category = category_map.get(resp.status_code, ErrorCategory.SERVER_ERROR)
        is_retryable = resp.status_code >= 500 or resp.status_code == 429

        message = f"HTTP {resp.status_code}"
        try:
            body = resp.json()
            if isinstance(body, dict) and (msg := body.get("message") or body.get("error")):
                message = str(msg)
        except (ValueError, AttributeError):
            pass

        return ApiResult.from_error(
            category, message,
            status_code=resp.status_code,
            provider=self.PROVIDER,
            is_retryable=is_retryable,
        )
