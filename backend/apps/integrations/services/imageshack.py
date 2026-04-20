from __future__ import annotations

from .base import AbstractServiceDefinition, ServiceField
from .registry import register_service


@register_service
class ImageShackService(AbstractServiceDefinition):
    """ImageShack image hosting service — used for album-based image hosting."""

    service_type = 'image'
    display_name = 'ImageShack'

    @classmethod
    def get_fields(cls) -> list[ServiceField]:
        return [
            ServiceField('api_key', 'API Key', 'password', required=True,
                         help_text='ImageShack API key'),
            ServiceField('album_prefix', 'Album Prefix', 'text', required=False,
                         help_text='Prefix for auto-generated album names (default: AC)'),
        ]

    @classmethod
    def build_client(cls, credential):
        """Build an ImageShackFacade from a ServiceCredential instance."""
        from apis_sdk.factories.imageshack_factory import ImageShackFactory
        from apis_sdk.infrastructure.http.requests_transport import RequestsTransport

        creds = credential.credentials or {}
        transport = RequestsTransport()

        return ImageShackFactory.create(
            api_key=creds.get('api_key', ''),
            transport=transport,
        )

    @classmethod
    def test_connection(cls, client) -> tuple[bool, str]:
        # ImageShack has no lightweight ping endpoint.
        # If build_client succeeded and api_key is set, consider it configured.
        if client.api_key:
            return True, "API key configured. (No ping endpoint available — will verify on first upload.)"
        return False, "API key is empty."
