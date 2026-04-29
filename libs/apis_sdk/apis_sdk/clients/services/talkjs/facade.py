"""
TalkJS high-level facade.

Provides a clean consumer-facing API for TalkJS operations.
Extracts and normalizes messages from the raw TalkJS data structures.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.result import ApiResult
from apis_sdk.clients.services.talkjs.client import TalkJsClient


class TalkJsMessage:
    """Lightweight message container."""

    __slots__ = ("id", "text", "sender_id", "created_at", "type", "custom")

    def __init__(
        self,
        id: str,
        text: str,
        sender_id: str,
        created_at: int,
        type: str = "UserMessage",
        custom: dict[str, Any] | None = None,
    ) -> None:
        self.id = id
        self.text = text
        self.sender_id = sender_id
        self.created_at = created_at
        self.type = type
        self.custom = custom or {}

    def __repr__(self) -> str:
        return f"TalkJsMessage(sender={self.sender_id!r}, text={self.text!r})"


class TalkJsFacade:
    """
    High-level TalkJS interface.

    Wraps the low-level TalkJsClient and provides:
    - get_messages(): flat list of messages for a conversation
    - send_message(): send a text message
    - get_boken(): retrieve auth token

    All methods return ApiResult — no exceptions escape.
    """

    def __init__(self, client: TalkJsClient) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def get_messages(
        self,
        conversation_id: str,
        external_conv_id: str | None = None,
    ) -> ApiResult[list[TalkJsMessage]]:
        """Fetch messages for a conversation, returned as a sorted list.

        Args:
            conversation_id: TalkJS internal conversation ID.
            external_conv_id: External conversation ID (UUID).
        """
        try:
            result = self._client.fetch_chatbox(
                conversation_id, external_conv_id,
            )
        except Exception as exc:
            return self._error(exc)

        if not result.ok:
            return ApiResult.from_error(
                result.error.category if result.error else ErrorCategory.UNKNOWN,
                result.error.message if result.error else "Unknown error",
                provider="talkjs",
            )

        raw = result.data or {}
        messages_data = raw.get("MESSAGES", {})
        conv_messages = messages_data.get(conversation_id, {})
        dtos = conv_messages.get("dtos", {})

        messages: list[TalkJsMessage] = []
        for msg_id, msg in dtos.items():
            messages.append(TalkJsMessage(
                id=msg.get("id", msg_id),
                text=msg.get("text", ""),
                sender_id=msg.get("senderId", ""),
                created_at=msg.get("createdAt", 0),
                type=msg.get("type", "UserMessage"),
                custom=msg.get("custom"),
            ))

        messages.sort(key=lambda m: m.created_at)
        return ApiResult.success(messages, status_code=result.status_code)

    def get_raw_chatbox(
        self,
        conversation_id: str,
        external_conv_id: str | None = None,
    ) -> ApiResult[dict[str, Any]]:
        """Fetch raw chatbox data (MESSAGES, SIDES, NYMS) without parsing."""
        try:
            return self._client.fetch_chatbox(conversation_id, external_conv_id)
        except Exception as exc:
            return self._error(exc)

    # ------------------------------------------------------------------
    # Inbox
    # ------------------------------------------------------------------

    def get_inbox(self) -> ApiResult[dict[str, Any]]:
        """Fetch inbox (conversation list)."""
        try:
            return self._client.fetch_inbox()
        except Exception as exc:
            return self._error(exc)

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def send_message(
        self,
        conversation_id: str,
        text: str,
    ) -> ApiResult[dict[str, Any]]:
        """Send a text message to a conversation."""
        try:
            return self._client.send_message(conversation_id, text)
        except Exception as exc:
            return self._error(exc)

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def get_boken(self, signature: str) -> ApiResult[dict[str, Any]]:
        """Retrieve TalkJS auth token (boken) using a signature."""
        try:
            return self._client.get_boken(signature)
        except Exception as exc:
            return self._error(exc)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _error(exc: Exception) -> ApiResult[Any]:
        return ApiResult.from_error(
            ErrorCategory.UNKNOWN,
            f"Unexpected TalkJS facade error: {exc}",
            provider="talkjs",
            is_retryable=False,
        )
