from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apis_sdk.factories.lzt_factory import LztFactory

from .base import AbstractProvider, CredentialField
from .registry import register_provider

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationCredential


@register_provider
class LztProvider(AbstractProvider):
    """LZT Market provider — source (buy) platform only."""

    provider_name = 'lzt'
    display_name = 'LZT Market'

    @classmethod
    def get_credential_fields(cls) -> list[CredentialField]:
        return [
            CredentialField('api_key', 'API Key', field_type='password'),
        ]

    def build_client(self, credential: IntegrationCredential, *, proxy_pool=None, proxy_group=None) -> Any:
        creds = credential.credentials
        transport = self._create_transport()
        return LztFactory.create(
            token=creds.get('api_key', ''),
            transport=transport,
            proxy_pool=proxy_pool,
        )

    def fetch_products(self, client: Any, **kwargs) -> Any:
        return client.get_user_orders(**kwargs)

    def create_listing(self, client: Any, product_data: dict) -> Any:
        raise NotImplementedError("LZT is used as a source platform only")

    def update_listing(self, client: Any, external_id: str, product_data: dict) -> Any:
        raise NotImplementedError("LZT is used as a source platform only")

    def delete_listing(self, client: Any, external_id: str) -> Any:
        raise NotImplementedError("LZT is used as a source platform only")

    def fetch_orders(self, client: Any, **kwargs) -> Any:
        return client.get_user_orders(**kwargs)
