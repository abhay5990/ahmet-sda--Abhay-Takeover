from __future__ import annotations

from .base import AbstractServiceDefinition, ServiceField
from .registry import register_service


@register_service
class TelegramBotService(AbstractServiceDefinition):
    """Telegram Bot — used for system notification broadcasts.

    Credentials:
        bot_token : Bot API token from @BotFather
        chat_id   : Target group/channel chat ID (e.g. "-1001234567890")
    """

    service_type = 'telegram'
    display_name = 'Telegram Bot'

    @classmethod
    def get_fields(cls) -> list[ServiceField]:
        return [
            ServiceField(
                'bot_token', 'Bot Token', 'password', required=True,
                help_text='Telegram Bot API token from @BotFather',
            ),
            ServiceField(
                'chat_id', 'Chat ID', 'text', required=True,
                help_text='Target group or channel chat ID (e.g. -1001234567890)',
            ),
        ]

    @classmethod
    def build_client(cls, credential) -> object:
        """Build a TelegramClient from a ServiceCredential instance."""
        from apis_sdk.clients.services.telegram.client import TelegramClient
        from apis_sdk.infrastructure.http.requests_transport import RequestsTransport

        creds = credential.credentials or {}
        return TelegramClient(
            bot_token=creds.get('bot_token', ''),
            transport=RequestsTransport(),
        )

    @classmethod
    def test_connection(cls, client) -> tuple[bool, str]:
        """Verify bot token via getMe."""
        result = client.get_me()
        if result.ok:
            username = result.data.get('username', '?')
            return True, f"Connected as @{username}"
        return False, f"Connection failed: {result.error}"
