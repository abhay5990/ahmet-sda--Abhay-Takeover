from __future__ import annotations

from .base import AbstractServiceDefinition, ServiceField
from .registry import register_service


@register_service
class RobloxService(AbstractServiceDefinition):
    """Roblox public API service.

    No API key required — public endpoints.
    Proxy URL is needed for regions where Roblox is blocked.
    """

    service_type = 'roblox'
    display_name = 'Roblox API'

    @classmethod
    def get_fields(cls) -> list[ServiceField]:
        return [
            ServiceField(
                name='proxy_url',
                label='Proxy URL',
                field_type='text',
                required=False,
                help_text='HTTP/SOCKS proxy for Roblox API (e.g. socks5://host:port). Required in Turkey.',
            ),
        ]

    @classmethod
    def build_client(cls, credential):
        """Build a RobloxFacade from a ServiceCredential instance."""
        from apis_sdk.clients.services.roblox.client import RobloxClient
        from apis_sdk.clients.services.roblox.config import RobloxConfig
        from apis_sdk.clients.services.roblox.facade import RobloxFacade
        from apis_sdk.infrastructure.http.requests_transport import RequestsTransport

        creds = credential.credentials or {}
        proxy_url = creds.get('proxy_url') or None

        config = RobloxConfig(proxy_url=proxy_url)
        transport = RequestsTransport()
        client = RobloxClient(config, transport)
        return RobloxFacade(client)

    @classmethod
    def test_connection(cls, client) -> tuple[bool, str]:
        result = client.resolve_username('Roblox')
        if result.ok:
            return True, f"Connected — resolved user ID: {result.data.user_id}"
        return False, result.error.message if result.error else "API returned an error."
