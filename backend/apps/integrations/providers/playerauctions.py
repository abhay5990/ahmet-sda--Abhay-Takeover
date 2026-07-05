from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, Any

from apis_sdk.clients.marketplaces.playerauctions.encryption import (
    PAPasswordEncryptor,
)
from apis_sdk.clients.marketplaces.playerauctions.models import (
    PlayerAuctionsCancelRequest,
)
from apis_sdk.factories.playerauctions_factory import PlayerAuctionsFactory
from apis_sdk.factories.pa_official_factory import PAOfficialFactory
from apis_sdk.infrastructure.logging.logger import StdlibLogger

from .base import AbstractProvider, CredentialField
from .registry import register_provider

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationCredential

logger = logging.getLogger(__name__)

# Module-level encryptor — key loaded once, reused for all requests.
_encryptor = PAPasswordEncryptor()


# ---------------------------------------------------------------------------
# Composite client — unified interface over official + legacy facades
# ---------------------------------------------------------------------------


class PACompositeClient:
    """Wraps official + legacy PA facades behind the legacy interface.

    Routing:
    - Offer ops (create, cancel, list, hide/show, bulk) → official API
    - Order ops (list_seller_orders, get_order_details) → legacy API

    The provider methods call the same duck-typed interface as before;
    this wrapper translates to the correct facade internally.
    """

    # Signals that the caller should NOT RSA-encrypt passwords.
    # Official API accepts plain text — encryption is legacy-only.
    needs_password_encryption = False

    def __init__(self, official_facade: Any, legacy_facade: Any) -> None:
        self._official = official_facade
        self._legacy = legacy_facade

    # --- Offer reads (→ official) ---

    def list_offers(self, **kwargs: Any) -> Any:
        return self._official.list_offers(**kwargs)

    def get_offer_details(self, offer_id: str, **kwargs: Any) -> Any:
        """Map legacy get_offer_details to official get_offer.

        Legacy uses string offer_id, official uses (product_type, int).
        Default product_type="account" since that's all the pipeline
        currently produces.
        """
        product_type = kwargs.pop("product_type", "account")
        return self._official.get_offer(product_type, int(offer_id), **kwargs)

    # --- Offer writes (→ official) ---

    def create_offer(
        self,
        payload: dict[str, Any] | None = None,
        *,
        proxy_group: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Translate legacy create_offer(payload=) to official create_offer(product_type, payload)."""
        if payload is None:
            payload = kwargs.get("payload", {})
        # Extract product_type from payload; default "account" (all current games)
        product_type = payload.pop("productType", "account")
        return self._official.create_offer(product_type, payload, proxy_group=proxy_group)

    def cancel_offers(
        self,
        request: PlayerAuctionsCancelRequest | None = None,
        *,
        offer_ids: list[int] | None = None,
        proxy_group: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Accept both legacy (request model) and official (offer_ids) calling conventions."""
        if request is not None:
            offer_ids = request.offer_ids
        return self._official.cancel_offers(offer_ids=offer_ids, proxy_group=proxy_group)

    def set_display_status(self, **kwargs: Any) -> Any:
        return self._official.set_display_status(**kwargs)

    # --- Bulk (→ official) ---

    def bulk_upload(self, file_path: str, **kwargs: Any) -> Any:
        return self._official.bulk_upload(file_path, **kwargs)

    # --- Game metadata (→ official) ---

    def game_account_servers(self, game_id: int, **kwargs: Any) -> Any:
        product_type = kwargs.pop("product_type", "account")
        return self._official.game_servers(game_id, product_type, **kwargs)

    # --- Auth management ---

    def reset_auth_failure(self) -> None:
        """Reset auth failure flags on both facades."""
        if hasattr(self._legacy, 'reset_auth_failure'):
            self._legacy.reset_auth_failure()

    # --- Orders (→ legacy, official API has no order endpoints) ---

    def list_seller_orders(self, **kwargs: Any) -> Any:
        return self._legacy.list_seller_orders(**kwargs)

    def get_order_details(self, order_id: str, **kwargs: Any) -> Any:
        return self._legacy.get_order_details(order_id, **kwargs)


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


@register_provider
class PlayerAuctionsProvider(AbstractProvider):
    """PlayerAuctions marketplace provider — sell (target) platform.

    Supports two auth modes:

    1. **Official API** (preferred): HMAC-SHA256 via api_key + secret_key.
       Returns a ``PACompositeClient`` that routes offer ops through the
       official API and order ops through the legacy API.
    2. **Legacy API**: Browser-based JWT via Puppeteer microservice.
       Returns the legacy ``PlayerAuctionsFacade`` directly.
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
                help_text='PlayerAuctions access token (JWT) — auto-refreshed via microservice. Not needed if using Official API.',
            ),
            CredentialField(
                'api_key', 'API Key (Official)',
                field_type='text',
                required=False,
                help_text='Official Seller API key (from PA API Key Management). Leave blank to use legacy auth.',
            ),
            CredentialField(
                'secret_key', 'Secret Key (Official)',
                field_type='password',
                required=False,
                help_text='Official Seller API secret key (shown only once at creation). Leave blank to use legacy auth.',
            ),
        ]

    def build_client(self, credential: IntegrationCredential, *, proxy_pool=None, proxy_group=None) -> Any:
        creds = credential.credentials
        transport = self._create_transport()

        # Closure that persists refreshed tokens to DB
        persist_callback = _make_persist_callback(credential.pk)

        api_key = creds.get('api_key', '')
        secret_key = creds.get('secret_key', '')

        if api_key and secret_key:
            # Official + legacy composite: offers via official, orders via legacy
            logger.info("Using official PA Seller API (HMAC-SHA256) for %s", credential.account.name)
            official = PAOfficialFactory.create(
                api_key=api_key,
                secret_key=secret_key,
                transport=transport,
                proxy_pool=proxy_pool,
                logger=StdlibLogger("apis_sdk.playerauctions_official"),
            )
            legacy = PlayerAuctionsFactory.create(
                username=creds.get('username', ''),
                password=creds.get('password', ''),
                access_token=creds.get('access_token', '') or creds.get('bearer_token', ''),
                cookie=creds.get('cookie', ''),
                user_agent=creds.get('user_agent', ''),
                transport=transport,
                proxy_pool=proxy_pool,
                proxy_group=proxy_group,
                on_refresh=persist_callback,
                logger=StdlibLogger("apis_sdk.playerauctions"),
            )
            return PACompositeClient(official_facade=official, legacy_facade=legacy)

        # Legacy-only: browser-based JWT auth via Puppeteer microservice
        return PlayerAuctionsFactory.create(
            username=creds.get('username', ''),
            password=creds.get('password', ''),
            access_token=creds.get('access_token', '') or creds.get('bearer_token', ''),
            cookie=creds.get('cookie', ''),
            user_agent=creds.get('user_agent', ''),
            transport=transport,
            proxy_pool=proxy_pool,
            proxy_group=proxy_group,
            on_refresh=persist_callback,
            logger=StdlibLogger("apis_sdk.playerauctions"),
        )

    def fetch_products(self, client: Any, **kwargs) -> Any:
        return client.list_offers(**kwargs)

    def create_listing(self, client: Any, product_data: dict) -> Any:
        """Create a single PA offer via ``create_offer`` API.

        Handles the ``product_data`` envelope created by ``_post_with_backoff``
        (``{'payload': <api_json>, 'proxy_group': <str|None>}``).

        Password encryption is only applied for the legacy API client.
        The official API accepts plain text passwords.
        """
        payload = product_data.get('payload', product_data)
        proxy_group = product_data.get('proxy_group')

        if getattr(client, 'needs_password_encryption', True):
            payload = _encrypt_pa_passwords(payload)

        return client.create_offer(
            payload=payload,
            proxy_group=proxy_group,
        )

    def update_listing(self, client: Any, external_id: str, product_data: dict) -> Any:
        raise NotImplementedError(
            "PlayerAuctions does not support direct offer updates via API."
        )

    def delete_listing(self, client: Any, external_id: str) -> Any:
        return client.cancel_offers(
            PlayerAuctionsCancelRequest(offerIds=[int(external_id)])
        )

    def fetch_orders(self, client: Any, **kwargs) -> Any:
        return client.list_seller_orders(**kwargs)

    def fetch_order_details(self, client: Any, order_id: str) -> Any:
        """Fetch rich order detail for a single order."""
        return client.get_order_details(order_id=order_id)


def _make_persist_callback(credential_pk: int):
    """Create a closure that persists refreshed PA session data to DB.

    Called by PlayerAuctionsAuth.on_refresh after a successful token
    refresh.  Saves access_token, cookie, and user_agent so they
    survive app restarts.
    """
    def _persist(access_token: str, cookie: str, user_agent: str) -> None:
        from apps.integrations.models import IntegrationCredential

        try:
            cred = IntegrationCredential.objects.get(pk=credential_pk)
            cred.update_token(
                access_token=access_token,
                cookie=cookie,
                user_agent=user_agent,
            )
            logger.info(
                "Persisted refreshed PA session to DB (credential=%s)",
                credential_pk,
            )
        except IntegrationCredential.DoesNotExist:
            logger.warning(
                "Cannot persist PA token — credential %s not found",
                credential_pk,
            )
        except Exception as exc:
            logger.warning(
                "Failed to persist PA token to DB: %s", exc,
            )

    return _persist


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

    for field in ('password', 'retypePassword', 'parentalPassword'):
        value = encrypted_auto.get(field)
        if value is not None:
            encrypted_auto[field] = _encryptor.encrypt(value)

    result['autoDelivery'] = encrypted_auto
    return result
