from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apis_sdk.factories.g2g_factory import G2GFactory

from .base import AbstractProvider, CredentialField
from .registry import register_provider

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationCredential


@register_provider
class G2gProvider(AbstractProvider):
    """G2G marketplace provider — sell (target) platform."""

    provider_name = 'g2g'
    display_name = 'G2G'

    @classmethod
    def get_credential_fields(cls) -> list[CredentialField]:
        return [
            CredentialField('access_token', 'Access Token', field_type='password'),
            CredentialField('refresh_token', 'Refresh Token', field_type='password'),
            CredentialField('active_device_token', 'Device Token', field_type='password', required=False),
            CredentialField('long_lived_token', 'Long-Lived Token', field_type='password', required=False),
            CredentialField('seller_id', 'Seller ID'),
        ]

    def build_client(self, credential: IntegrationCredential, *, proxy_pool=None, proxy_group=None) -> Any:
        creds = credential.credentials
        transport = self._create_transport()
        return G2GFactory.create(
            transport=transport,
            access_token=creds.get('access_token', ''),
            refresh_token=creds.get('refresh_token', ''),
            active_device_token=creds.get('active_device_token', ''),
            long_lived_token=creds.get('long_lived_token', ''),
            seller_id=creds.get('seller_id', ''),
            proxy_pool=proxy_pool,
        )

    def fetch_products(self, client: Any, **kwargs) -> Any:
        return client.get_offers(**kwargs)

    def create_listing(self, client: Any, product_data: dict) -> Any:
        return client.create_offer(**product_data)

    def update_listing(self, client: Any, external_id: str, product_data: dict) -> Any:
        return client.update_offer(offer_id=external_id, **product_data)

    def delete_listing(self, client: Any, external_id: str) -> Any:
        return client.delete_offer(offer_id=external_id)

    def fetch_orders(self, client: Any, **kwargs) -> Any:
        return client.get_orders(**kwargs)
