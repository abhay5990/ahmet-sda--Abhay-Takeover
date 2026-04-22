from .base import AbstractServiceDefinition, ServiceField
from .registry import register_service


@register_service
class FirstMailService(AbstractServiceDefinition):
    """FirstMail email service (https://firstmail.ltd).

    Credentials:
        api_key  — FirstMail X-API-KEY (from https://firstmail.ltd/lk/api)
        base_url — optional override (default: https://firstmail.ltd/api/v1)
    """

    service_type = 'email'
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
