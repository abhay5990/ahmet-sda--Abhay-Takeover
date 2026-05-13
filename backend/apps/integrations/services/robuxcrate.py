from __future__ import annotations

from .base import AbstractServiceDefinition, ServiceField
from .registry import register_service


@register_service
class RobuxCrateService(AbstractServiceDefinition):
    """RobuxCrate game service.

    Credentials:
        api_key  — RobuxCrate API key
    """

    service_type = 'robuxcrate'
    display_name = 'RobuxCrate'

    @classmethod
    def get_fields(cls) -> list[ServiceField]:
        return [
            ServiceField(
                name='api_key',
                label='API Key',
                field_type='password',
                required=True,
                help_text='RobuxCrate dashboard → API Keys',
            ),
        ]

    @classmethod
    def build_client(cls, credential):
        """Build a RbxCrateFacade from a ServiceCredential instance."""
        from apis_sdk.clients.services.rbxcrate.client import RbxCrateClient
        from apis_sdk.clients.services.rbxcrate.config import RbxCrateConfig
        from apis_sdk.clients.services.rbxcrate.facade import RbxCrateFacade
        from apis_sdk.infrastructure.auth.api_key import ApiKeyAuth
        from apis_sdk.infrastructure.http.requests_transport import RequestsTransport

        creds = credential.credentials or {}
        api_key = creds.get('api_key', '')

        config = RbxCrateConfig(
            base_url=credential.base_url or 'https://rbxcrate.com/api',
        )
        auth = ApiKeyAuth(api_key=api_key)
        transport = RequestsTransport()
        client = RbxCrateClient(config, transport)
        return RbxCrateFacade(client, auth)

    @classmethod
    def test_connection(cls, client) -> tuple[bool, str]:
        result = client.get_stock()
        if result.ok:
            return True, "Connection successful!"
        return False, result.error.message if result.error else "API returned an error."
