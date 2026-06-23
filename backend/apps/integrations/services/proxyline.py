from .base import AbstractServiceDefinition, ServiceField
from .registry import register_service

_DEFAULT_BASE_URL = 'https://panel.proxyline.net/api'


@register_service
class ProxylineService(AbstractServiceDefinition):
    """Proxyline proxy provider (https://proxyline.net).

    Credentials:
        api_key  — Proxyline panel API key
        base_url — optional override (default: https://panel.proxyline.net/api)
    """

    service_type = 'proxyline'
    display_name = 'Proxyline'

    @classmethod
    def get_fields(cls) -> list[ServiceField]:
        return [
            ServiceField(
                name='api_key',
                label='API Key',
                field_type='password',
                required=True,
                help_text='Found in your Proxyline panel → API section',
            ),
            ServiceField(
                name='base_url',
                label='Base URL',
                field_type='url',
                required=False,
                help_text='Leave blank to use default: https://panel.proxyline.net/api',
            ),
        ]

    @classmethod
    def build_client(cls, credential) -> dict:
        """Return a plain credentials dict — Proxyline has no SDK."""
        creds = credential.credentials or {}
        return {
            'api_key': creds.get('api_key', ''),
            'base_url': credential.base_url or _DEFAULT_BASE_URL,
        }

    @classmethod
    def test_connection(cls, client: dict) -> tuple[bool, str]:
        """GET /proxies/ with api_key to verify credentials."""
        import requests as _requests

        api_key = client.get('api_key', '')
        if not api_key:
            return False, "API key is not configured."
        base_url = client.get('base_url', _DEFAULT_BASE_URL).rstrip('/')
        try:
            resp = _requests.get(
                f"{base_url}/proxies/",
                params={'api_key': api_key, 'count': 1},
                timeout=10,
            )
            if resp.status_code == 200:
                return True, "Connection successful!"
            if resp.status_code in (401, 403):
                return False, "Invalid API key."
            return False, f"API returned HTTP {resp.status_code}."
        except Exception as exc:
            return False, f"Connection failed: {exc}"
