from __future__ import annotations

from .base import AbstractServiceDefinition, ServiceField
from .registry import register_service


@register_service
class ImgurService(AbstractServiceDefinition):
    """Imgur image hosting — used for album image downloads (manual posting)."""

    service_type = 'imgur'
    display_name = 'Imgur'

    @classmethod
    def get_fields(cls) -> list[ServiceField]:
        return [
            ServiceField(
                'client_id', 'Client ID', 'password', required=True,
                help_text='Imgur API Client-ID (from https://api.imgur.com/oauth2/addclient).',
            ),
        ]

    @classmethod
    def build_client(cls, credential):
        from apis_sdk.factories.imgur_factory import ImgurFactory
        from apis_sdk.infrastructure.http.requests_transport import RequestsTransport

        creds = credential.credentials or {}
        return ImgurFactory.create(
            client_id=creds.get('client_id', ''),
            transport=RequestsTransport(),
        )

    @classmethod
    def test_connection(cls, client) -> tuple[bool, str]:
        result = client.get_credits()
        if result.ok:
            return True, f"Connected. Remaining credits: {result.data}"
        return False, f"Failed: {result.error}"
