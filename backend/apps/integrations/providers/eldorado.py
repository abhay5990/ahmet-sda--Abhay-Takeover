from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apis_sdk.factories.eldorado_factory import EldoradoFactory

from .base import AbstractProvider, CredentialField
from .registry import register_provider

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationCredential


@register_provider
class EldoradoProvider(AbstractProvider):
    """Eldorado marketplace provider — sell (target) platform."""

    provider_name = 'eldorado'
    display_name = 'Eldorado'

    @classmethod
    def get_credential_fields(cls) -> list[CredentialField]:
        return [
            CredentialField('email', 'Email'),
            CredentialField('password', 'Password', field_type='password'),
            CredentialField(
                'id_token', 'ID Token',
                field_type='readonly', required=False, read_only=True,
                help_text='Auto-filled after Cognito auth',
            ),
        ]

    def build_client(self, credential: IntegrationCredential, *, proxy_pool=None, proxy_group=None) -> Any:
        creds = credential.credentials
        transport = self._create_transport()
        return EldoradoFactory.create(
            email=creds.get('email', ''),
            password=creds.get('password', ''),
            id_token=creds.get('id_token', ''),
            enable_cognito_auth=bool(creds.get('email') and creds.get('password')),
            transport=transport,
            proxy_pool=proxy_pool,
        )

    def fetch_products(self, client: Any, **kwargs) -> Any:
        return client.search_my_offers(**kwargs)

    def create_listing(self, client: Any, product_data: dict) -> Any:
        return client.create_offer(**product_data)

    def update_listing(self, client: Any, external_id: str, product_data: dict) -> Any:
        return client.update_offer(offer_id=external_id, **product_data)

    def delete_listing(self, client: Any, external_id: str) -> Any:
        return client.delete_offer(offer_id=external_id)

    def fetch_orders(self, client: Any, **kwargs) -> Any:
        return client.get_seller_orders(**kwargs)

    def fetch_order_account_details(self, client: Any, order_id: str) -> dict | None:
        return client.get_order_account_details(order_id=order_id)

    def fetch_offer_account_details(self, client: Any, offer_id: str) -> Any:
        return client.get_offer_account_details(offer_id=offer_id)

    def get_listing_url(self, external_id: str) -> str | None:
        return f"https://www.eldorado.gg/offer/{external_id}"
