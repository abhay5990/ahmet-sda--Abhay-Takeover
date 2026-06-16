from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apis_sdk.factories.gameboost_factory import GameBoostFactory

from .base import AbstractProvider, CredentialField
from .registry import register_provider

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationCredential


@register_provider
class GameboostProvider(AbstractProvider):
    """Gameboost marketplace provider — sell (target) platform."""

    provider_name = 'gameboost'
    display_name = 'Gameboost'

    @classmethod
    def get_credential_fields(cls) -> list[CredentialField]:
        return [
            CredentialField('api_key', 'API Key', field_type='password'),
        ]

    def build_client(self, credential: IntegrationCredential, *, proxy_pool=None, proxy_group=None) -> Any:
        creds = credential.credentials
        transport = self._create_transport()
        return GameBoostFactory.create(
            token=creds.get('api_key', ''),
            transport=transport,
            proxy_pool=proxy_pool,
        )

    def fetch_products(self, client: Any, **kwargs) -> Any:
        return client.list_offers(**kwargs)

    def create_listing(self, client: Any, product_data: dict) -> Any:
        payload = product_data.get('payload', product_data)
        proxy_group = product_data.get('proxy_group')

        if 'credentials' in payload:
            return client.create_offer_with_credentials(
                payload=payload, proxy_group=proxy_group,
            )
        return client.create_offer(payload=payload, proxy_group=proxy_group)

    def update_listing(self, client: Any, external_id: str, product_data: dict) -> Any:
        return client.update_offer(account_id=external_id, payload=product_data)

    def delete_listing(self, client: Any, external_id: str) -> Any:
        return client.delete_offer(account_id=external_id)

    def fetch_orders(self, client: Any, **kwargs) -> Any:
        return client.list_orders(**kwargs)
