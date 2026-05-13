from .base import AbstractServiceDefinition, ServiceField
from .registry import register_service


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
