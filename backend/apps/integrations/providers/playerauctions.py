from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, Any

from apis_sdk.clients.marketplaces.playerauctions.encryption import (
    PAPasswordEncryptor,
)
from apis_sdk.factories.playerauctions_factory import PlayerAuctionsFactory
from apis_sdk.infrastructure.logging.logger import StdlibLogger

from .base import AbstractProvider, CredentialField
from .registry import register_provider

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationCredential

logger = logging.getLogger(__name__)

# Module-level encryptor — key loaded once, reused for all requests.
_encryptor = PAPasswordEncryptor()


@register_provider
class PlayerAuctionsProvider(AbstractProvider):
    """PlayerAuctions marketplace provider — sell (target) platform.

    Auth: Uses reactive token refresh via a local Puppeteer microservice.
    When a 401 is encountered, the SDK calls the PA Token Service to
    perform browser-based login and obtain a fresh JWT.
    Credentials must include ``username`` and ``password``.
    ``access_token`` is optional (auto-obtained on first 401).
    """

    provider_name = 'playerauctions'
    display_name = 'PlayerAuctions'

    @classmethod
    def get_credential_fields(cls) -> list[CredentialField]:
        return [
            CredentialField(
                'username', 'Username',
                field_type='text',
                required=True,
                help_text='PlayerAuctions username',
            ),
            CredentialField(
                'password', 'Password',
                field_type='password',
                required=True,
                help_text='PlayerAuctions password',
            ),
            CredentialField(
                'access_token', 'Access Token',
                field_type='password',
                required=False,
                help_text='PlayerAuctions access token (JWT) — auto-refreshed via microservice',
            ),
        ]

    def build_client(self, credential: IntegrationCredential, *, proxy_pool=None, proxy_group=None) -> Any:
        creds = credential.credentials
        transport = self._create_transport()

        return PlayerAuctionsFactory.create(
            username=creds.get('username', ''),
            password=creds.get('password', ''),
            access_token=creds.get('access_token', '') or creds.get('bearer_token', ''),
            transport=transport,
            proxy_pool=proxy_pool,
            proxy_group=proxy_group,
            logger=StdlibLogger("apis_sdk.playerauctions"),
        )

    def fetch_products(self, client: Any, **kwargs) -> Any:
        return client.list_offers(**kwargs)

    def create_listing(self, client: Any, product_data: dict) -> Any:
        """Create a single PA offer via ``create_offer`` API.

        Handles the ``product_data`` envelope created by ``_post_with_backoff``
        (``{'payload': <api_json>, 'proxy_group': <str|None>}``), encrypts
        password fields with PA's RSA public key, then delegates to the SDK.
        """
        payload = product_data.get('payload', product_data)
        proxy_group = product_data.get('proxy_group')

        encrypted_payload = _encrypt_pa_passwords(payload)

        return client.create_offer(
            payload=encrypted_payload,
            proxy_group=proxy_group,
        )

    def update_listing(self, client: Any, external_id: str, product_data: dict) -> Any:
        raise NotImplementedError(
            "PlayerAuctions does not support direct offer updates via API."
        )

    def delete_listing(self, client: Any, external_id: str) -> Any:
        from apis_sdk.clients.marketplaces.playerauctions.models import (
            PlayerAuctionsCancelRequest,
        )
        return client.cancel_offers(
            PlayerAuctionsCancelRequest(offerIds=[int(external_id)])
        )

    def fetch_orders(self, client: Any, **kwargs) -> Any:
        return client.list_seller_orders(**kwargs)

    def fetch_order_details(self, client: Any, order_id: str) -> Any:
        """Fetch rich order detail for a single order."""
        return client.get_order_details(order_id=order_id)


def _encrypt_pa_passwords(payload: dict[str, Any]) -> dict[str, Any]:
    """Encrypt password fields in a PA ``create_offer`` API payload.

    Fields encrypted (per PA template ``"encrypted": true``):
    - ``autoDelivery.password`` / ``retypePassword``
    - ``autoDelivery.parentalPassword`` (if present)
    - ``autoDelivery.securityAnswer`` / ``retypeSecurityAnswer`` (if present)

    Returns a shallow copy so the original payload is not mutated.
    """
    auto = payload.get('autoDelivery')
    if not auto:
        return payload

    result = copy.copy(payload)
    encrypted_auto = dict(auto)

    for field in ('password', 'retypePassword', 'parentalPassword',
                  'securityAnswer', 'retypeSecurityAnswer'):
        value = encrypted_auto.get(field)
        if value is not None:
            encrypted_auto[field] = _encryptor.encrypt(value)

    result['autoDelivery'] = encrypted_auto
    return result
