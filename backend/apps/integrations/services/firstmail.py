from .base import AbstractServiceDefinition, ServiceField
from .registry import register_service


@register_service
class FirstMailService(AbstractServiceDefinition):
    """FirstMail email service (https://firstmail.ltd).

    Credentials:
        api_key  — FirstMail X-API-KEY (from https://firstmail.ltd/lk/api)
        base_url — optional override (default: https://firstmail.ltd/api/v1)
    """

    service_type = 'firstmail'
    display_name = 'FirstMail'

    @classmethod
    def get_fields(cls) -> list[ServiceField]:
        return [
            ServiceField(
                name='api_key',
                label='API Key (X-API-KEY)',
                field_type='password',
                required=True,
                help_text='Generate at https://firstmail.ltd/lk/api',
            ),
            ServiceField(
                name='base_url',
                label='Base URL',
                field_type='url',
                required=False,
                help_text='Leave blank to use default: https://firstmail.ltd/api/v1',
            ),
        ]

    @classmethod
    def build_client(cls, credential) -> dict:
        """Return a plain credentials dict — no dedicated ping endpoint in FirstMail SDK."""
        creds = credential.credentials or {}
        return {
            'api_key': creds.get('api_key', ''),
        }

    @classmethod
    def test_connection(cls, client: dict) -> tuple[bool, str]:
        """FirstMail has no ping/status endpoint — verify api_key is present."""
        if client.get('api_key'):
            return True, "API key configured. (No ping endpoint available — will verify on first use.)"
        return False, "API key is not configured."
