from __future__ import annotations

from .base import AbstractServiceDefinition, ServiceField
from .registry import register_service


@register_service
class DropboxService(AbstractServiceDefinition):
    """Dropbox cloud storage service — used for media image hosting."""

    service_type = 'dropbox'
    display_name = 'Dropbox'

    @classmethod
    def get_fields(cls) -> list[ServiceField]:
        return [
            ServiceField('access_token', 'Access Token', 'password', required=True,
                         help_text='Short-lived access token (auto-refreshed)'),
            ServiceField('refresh_token', 'Refresh Token', 'password', required=True,
                         help_text='Long-lived refresh token for OAuth2'),
            ServiceField('app_key', 'App Key', 'text', required=True,
                         help_text='Dropbox app key (client_id)'),
            ServiceField('app_secret', 'App Secret', 'password', required=True,
                         help_text='Dropbox app secret (client_secret)'),
            ServiceField('upload_folder', 'Upload Folder', 'text', required=False,
                         help_text='Dropbox folder path for uploads (default: /media)'),
            ServiceField('token_expires_at', 'Token Expires At', 'readonly', required=False,
                         help_text='Auto-updated by system after token refresh'),
        ]

    @classmethod
    def build_client(cls, credential):
        """Build a DropboxFacade from a ServiceCredential instance."""
        from apis_sdk.factories.dropbox_factory import DropboxFactory
        from apis_sdk.infrastructure.http.requests_transport import RequestsTransport

        creds = credential.credentials or {}
        transport = RequestsTransport()

        return DropboxFactory.create(
            access_token=creds.get('access_token', ''),
            transport=transport,
            upload_folder=creds.get('upload_folder', '/media'),
        )

    @classmethod
    def test_connection(cls, client) -> tuple[bool, str]:
        result = client.get_metadata("/")
        if result.ok:
            return True, "Connection successful!"
        return False, result.error.message if result.error else "API returned an error."
