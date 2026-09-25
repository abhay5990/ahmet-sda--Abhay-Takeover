from __future__ import annotations

import base64
import copy
import json
import logging
import os
import uuid
from typing import TYPE_CHECKING, Any

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from apis_sdk.core.enums import ErrorCategory
from apis_sdk.core.result import ApiResult
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

# The seller mailbox and official credentials used for the Mart account are
# intentionally scoped to this known relay-store identifier.  Shop keeps its
# existing configuration and is never opted in by this code path.
_OFFICIAL_MART_STORE_SLUGS = frozenset({"csgosmurfkings", "ezsmurfmart"})

# Module-level encryptor — key loaded once, reused for all requests.
_encryptor = PAPasswordEncryptor()

_MCT_MART_DELEGATION_PATH = '/api/sda/pa-mart/delegate'
_MCT_MART_DELEGATION_TIMEOUT = 45
_MCT_MART_OFFICIAL_OFFER_SNAPSHOT_PATH = '/api/sda/pa-mart/official-active-offers'


def _env_flag_enabled(value: str | None) -> bool:
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'on'}


def _mart_mct_delegation_enabled(env: dict[str, str] | None = None) -> bool:
    runtime_env = os.environ if env is None else env
    return _env_flag_enabled(runtime_env.get('PA_MART_MCT_DELEGATION_ENABLED'))


def _get_mct_mart_delegation_config(
    env: dict[str, str] | None = None,
) -> tuple[str, str, bytes]:
    """Load only the protected SDA→MCT Mart delegation configuration.

    This key protects the account-offer payload in transit and is separate from
    every PlayerAuctions credential. The payload is AES-GCM encrypted before the
    private MCT bridge request; only MCT's whitelisted worker decrypts it.
    """
    runtime_env = os.environ if env is None else env
    url = str(runtime_env.get('PA_MART_MCT_DELEGATION_URL') or '').strip().rstrip('/')
    token = str(runtime_env.get('PA_MART_MCT_DELEGATION_TOKEN') or '').strip()
    raw_key = str(runtime_env.get('PA_MART_MCT_DELEGATION_KEY') or '').strip()
    if not url.endswith(_MCT_MART_DELEGATION_PATH) or not token or not raw_key:
        raise RuntimeError('Mart MCT delegation environment configuration is incomplete')
    try:
        key = base64.b64decode(raw_key.encode('ascii'), validate=True)
    except Exception as exc:
        raise RuntimeError('Mart MCT delegation key is invalid') from exc
    if len(key) != 32:
        raise RuntimeError('Mart MCT delegation key is invalid')
    return url, token, key


class MctMartDelegationClient:
    """Mart-only encrypted caller for the whitelisted MCT official API worker.

    It has no official API key, browser credentials, bearer-token route, or relay
    route. An ambiguous transport/server outcome remains unknown so SDA cannot
    safely retry the create path and make a duplicate listing.
    """

    needs_password_encryption = False

    def __init__(self, *, url: str, token: str, key: bytes) -> None:
        self._url = url
        self._token = token
        self._key = key
        self._official_offer_snapshot_url = (
            f"{url[:-len(_MCT_MART_DELEGATION_PATH)]}"
            f"{_MCT_MART_OFFICIAL_OFFER_SNAPSHOT_PATH}"
        )

    def uses_official_offer_api_only(self) -> bool:
        return True

    def uses_relay_browser_order_reads(self) -> bool:
        return False

    def uses_mct_official_offer_snapshot(self) -> bool:
        """True only for Mart's existing-listing snapshot synchronization.

        The offer sync service uses this signal to request exact SDA-owned offer
        IDs from the durable MCT Official API cache. It never asks MCT to
        discover listings by game, title, or credential.
        """
        return True

    def _encrypted_envelope(self, payload: dict[str, Any]) -> dict[str, Any]:
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key).encrypt(nonce, json.dumps(payload, separators=(',', ':')).encode('utf-8'), None)
        return {
            'v': 1,
            'iv': base64.b64encode(nonce).decode('ascii'),
            'data': base64.b64encode(ciphertext[:-16]).decode('ascii'),
            'tag': base64.b64encode(ciphertext[-16:]).decode('ascii'),
        }

    def _delegate(self, action: str, payload: dict[str, Any]) -> ApiResult[dict[str, Any]]:
        request_id = uuid.uuid4().hex + uuid.uuid4().hex[:8]
        try:
            response = requests.post(
                self._url,
                json={'requestId': request_id, 'action': action, 'envelope': self._encrypted_envelope(payload)},
                headers={'X-Bridge-Secret': self._token, 'Content-Type': 'application/json'},
                timeout=_MCT_MART_DELEGATION_TIMEOUT,
            )
            data = response.json() if response.content else {}
        except (requests.RequestException, ValueError):
            return ApiResult.from_error(
                ErrorCategory.SERVER_ERROR,
                'MCT Mart delegation transport outcome is unknown; reconcile the request before retrying.',
                provider='playerauctions', is_retryable=True,
                details={'request_id': request_id, 'delegation_outcome': 'unknown'},
            )
        if response.ok and data.get('ok'):
            return ApiResult.success({'offer_id': str(data.get('offerId') or ''), 'request_id': request_id}, status_code=response.status_code)
        unknown = response.status_code >= 500 or data.get('status') in {'pending', 'unknown'}
        return ApiResult.from_error(
            ErrorCategory.SERVER_ERROR if unknown else ErrorCategory.VALIDATION,
            'MCT Mart delegation outcome is unknown; reconcile the request before retrying.' if unknown else 'MCT Mart delegation rejected the request before a confirmed marketplace write.',
            provider='playerauctions', is_retryable=unknown,
            details={
                'request_id': request_id,
                'delegation_outcome': 'unknown' if unknown else 'rejected',
                'error_code': str(data.get('errorCode') or data.get('error') or 'mct_delegation_rejected')[:96],
            },
        )

    def list_offers(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        listing_status: str = '',
        offer_ids: list[int] | None = None,
        **_kwargs: Any,
    ) -> ApiResult[list[dict[str, Any]]]:
        """Read only SDA-known Active Mart offers from MCT's fresh snapshot.

        This call contains no PlayerAuctions key, secret, username, password,
        browser cookie, proxy, or delivery data. The MCT route accepts exact
        offer IDs only and returns safe summary fields from its Official API
        cache. Hidden offers are deliberately outside this active-only cache.
        """
        if str(listing_status or 'Active').strip().lower() not in {'', 'active'}:
            return ApiResult.success(
                [],
                meta={'pagination': {'current_page': page, 'total_pages': page}},
            )
        normalized_ids: list[int] = []
        for value in offer_ids or []:
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0 and parsed not in normalized_ids:
                normalized_ids.append(parsed)
        if not normalized_ids:
            return ApiResult.from_error(
                ErrorCategory.VALIDATION,
                'Mart Official active-offer snapshot requires SDA-known offer IDs.',
                provider='playerauctions',
            )
        try:
            response = requests.post(
                self._official_offer_snapshot_url,
                json={'offerIds': normalized_ids, 'pageIndex': page, 'pageSize': page_size},
                headers={'X-Bridge-Secret': self._token, 'Content-Type': 'application/json'},
                timeout=_MCT_MART_DELEGATION_TIMEOUT,
            )
            data = response.json() if response.content else {}
        except (requests.RequestException, ValueError):
            return ApiResult.from_error(
                ErrorCategory.SERVER_ERROR,
                'Mart Official active-offer snapshot is unavailable; no PlayerAuctions request was attempted.',
                provider='playerauctions',
                is_retryable=True,
            )
        if response.ok and data.get('ok') and isinstance(data.get('offers'), list):
            pagination = data.get('pagination') if isinstance(data.get('pagination'), dict) else {}
            return ApiResult.success(
                [offer for offer in data['offers'] if isinstance(offer, dict)],
                status_code=response.status_code,
                meta={
                    'pagination': {
                        'current_page': pagination.get('currentPage', page),
                        'total_pages': pagination.get('totalPages', page),
                    },
                    'snapshot_refreshed_at': str(data.get('snapshotRefreshedAt') or ''),
                    'snapshot_age_seconds': data.get('snapshotAgeSeconds'),
                },
            )
        error_code = str(data.get('error') or 'official_mart_snapshot_unavailable')[:96]
        return ApiResult.from_error(
            ErrorCategory.SERVER_ERROR,
            f'Mart Official active-offer snapshot unavailable: {error_code}',
            provider='playerauctions',
            status_code=response.status_code,
            is_retryable=True,
            details={'error_code': error_code},
        )

    def get_offer_details(
        self,
        offer_id: str | int,
        **_kwargs: Any,
    ) -> ApiResult[dict[str, Any]]:
        """Verify one Mart offer against the fresh active-only MCT snapshot.

        This compatibility method exists for the pool checker. It performs no
        PlayerAuctions detail request and does not reveal credentials. A 404 is
        emitted only after the authenticated MCT cache route has accepted the
        exact known ID and returned a complete fresh snapshot without it.
        """
        try:
            normalized_id = int(offer_id)
        except (TypeError, ValueError):
            return ApiResult.from_error(
                ErrorCategory.VALIDATION,
                'Mart offer verification requires a numeric offer ID.',
                provider='playerauctions',
            )
        if normalized_id <= 0:
            return ApiResult.from_error(
                ErrorCategory.VALIDATION,
                'Mart offer verification requires a numeric offer ID.',
                provider='playerauctions',
            )
        result = self.list_offers(
            offer_ids=[normalized_id],
            listing_status='Active',
            page=1,
            page_size=1,
        )
        if not result.ok:
            return ApiResult.failure(result.error) if result.error else ApiResult.from_error(
                ErrorCategory.SERVER_ERROR,
                'Mart Official active-offer snapshot is unavailable.',
                provider='playerauctions',
                is_retryable=True,
            )
        for offer in result.data or []:
            if str(offer.get('offerId') or offer.get('offer_id') or '') == str(normalized_id):
                return ApiResult.success(offer, status_code=result.status_code, meta=result.meta)
        return ApiResult.from_error(
            ErrorCategory.NOT_FOUND,
            'Mart offer is absent from the fresh Official active-offer snapshot.',
            provider='playerauctions',
            status_code=404,
        )

    def create_offer(self, product_type: str, payload: dict[str, Any], **_kwargs: Any) -> ApiResult[dict[str, Any]]:
        if product_type != 'account':
            return ApiResult.from_error(ErrorCategory.VALIDATION, 'MCT Mart delegation only supports account offers.', provider='playerauctions')
        return self._delegate('create', payload)

    def edit_offer(self, product_type: str, payload: dict[str, Any], **_kwargs: Any) -> ApiResult[dict[str, Any]]:
        if product_type != 'account':
            return ApiResult.from_error(ErrorCategory.VALIDATION, 'MCT Mart delegation only supports account offers.', provider='playerauctions')
        return self._delegate('update', payload)

    def cancel_offers(self, request: PlayerAuctionsCancelRequest | None = None, *, offer_ids: list[int] | None = None, **_kwargs: Any) -> ApiResult[dict[str, Any]]:
        resolved = request.offer_ids if request is not None else offer_ids or []
        return self._delegate('cancel', {'offerIds': [int(value) for value in resolved]})

    def list_seller_orders(self, **_kwargs: Any) -> ApiResult[Any]:
        return ApiResult.from_error(ErrorCategory.VALIDATION, 'Mart seller-order reads stay on the Gmail order bridge.', provider='playerauctions')

    def get_order_details(self, **_kwargs: Any) -> ApiResult[Any]:
        return ApiResult.from_error(ErrorCategory.VALIDATION, 'Mart seller-order reads stay on the Gmail order bridge.', provider='playerauctions')


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

    def __init__(self, official_facade: Any, legacy_facade: Any | None = None) -> None:
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

    def edit_offer_in_browser(self, **kwargs: Any) -> Any:
        """Use the legacy browser session only where that lane is explicitly retained."""
        if self._legacy is None:
            raise RuntimeError(
                "Mart is configured for the official PlayerAuctions Offer API only; "
                "browser-session edits are disabled."
            )
        return self._legacy.edit_offer_in_browser(**kwargs)

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
        if self._legacy is not None and hasattr(self._legacy, 'reset_auth_failure'):
            self._legacy.reset_auth_failure()

    def refresh_relay_session(self) -> bool:
        """Get the current shared relay session before a seller-order poll."""
        if self._legacy is None:
            return False
        refresh = getattr(self._legacy, 'refresh_relay_session', None)
        if not callable(refresh):
            return False
        return bool(refresh())

    def uses_relay_browser_order_reads(self) -> bool:
        """Expose Mart's relay-only order-read boundary to the sync service."""
        if self._legacy is None:
            return False
        uses_relay = getattr(self._legacy, 'uses_relay_browser_order_reads', None)
        return uses_relay() is True if callable(uses_relay) else False

    def uses_official_offer_api_only(self) -> bool:
        """True only for the Mart lane that must never create a browser session."""
        return self._legacy is None

    # --- Orders (→ legacy, official API has no order endpoints) ---

    def list_seller_orders(self, **kwargs: Any) -> Any:
        if self._legacy is None:
            return ApiResult.from_error(
                ErrorCategory.VALIDATION,
                "The documented PlayerAuctions Offer API does not expose seller-order reads for Mart.",
                provider='playerauctions',
            )
        return self._legacy.list_seller_orders(**kwargs)

    def get_order_details(self, order_id: str, **kwargs: Any) -> Any:
        if self._legacy is None:
            return ApiResult.from_error(
                ErrorCategory.VALIDATION,
                "The documented PlayerAuctions Offer API does not expose seller-order detail for Mart.",
                provider='playerauctions',
            )
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

        # Relay config — read from credential or fall back to defaults
        relay_url = creds.get('relay_url', 'http://35.231.166.148:3001')
        management_relay_url = creds.get('management_relay_url') or relay_url
        relay_secret = creds.get('relay_secret', 'pa-relay-secret-2026')
        # store_slug maps our internal account slug to the relay's store identifier
        store_slug = creds.get('store_slug', '') or credential.account.slug or ''

        # Mart-only cutover: the MCT worker has the approved official-API egress.
        # Do this before local official or legacy client construction so Mart
        # cannot create a browser session or browser-relay request in this mode.
        if _is_official_mart_credential(credential, creds) and _mart_mct_delegation_enabled():
            url, token, key = _get_mct_mart_delegation_config()
            logger.info('Mart PlayerAuctions account delegates official account-offer writes to MCT')
            return MctMartDelegationClient(url=url, token=token, key=key)

        api_key = creds.get('api_key', '')
        secret_key = creds.get('secret_key', '')

        if api_key and secret_key:
            # Mart is deliberately official-offer-API-only.  Do not instantiate
            # the legacy browser client: merely constructing it leaves a future
            # caller able to trigger the old relay/session path.
            logger.info("Using official PA Seller API (HMAC-SHA256) for %s", credential.account.name)
            official = PAOfficialFactory.create(
                api_key=api_key,
                secret_key=secret_key,
                transport=transport,
                proxy_pool=proxy_pool,
                logger=StdlibLogger("apis_sdk.playerauctions_official"),
            )
            if _is_official_mart_credential(credential, creds):
                logger.info("Mart PlayerAuctions account is official-offer-API-only; relay is disabled for this client")
                return PACompositeClient(official_facade=official)

            # Other accounts retain the previous mixed routing until separately
            # approved and migrated.
            legacy = PlayerAuctionsFactory.create(
                username=creds.get('username', ''),
                password=creds.get('password', ''),
                access_token=creds.get('access_token', '') or creds.get('bearer_token', ''),
                cookie=creds.get('cookie', ''),
                user_agent=creds.get('user_agent', ''),
                transport=transport,
                proxy_pool=proxy_pool,
                proxy_group=proxy_group,
                relay_url=relay_url,
                management_relay_url=management_relay_url,
                relay_secret=relay_secret,
                store_slug=store_slug,
                on_refresh=persist_callback,
                logger=StdlibLogger("apis_sdk.playerauctions"),
            )
            return PACompositeClient(official_facade=official, legacy_facade=legacy)

        # Legacy-only: browser-based JWT auth via relay
        return PlayerAuctionsFactory.create(
            username=creds.get('username', ''),
            password=creds.get('password', ''),
            access_token=creds.get('access_token', '') or creds.get('bearer_token', ''),
            cookie=creds.get('cookie', ''),
            user_agent=creds.get('user_agent', ''),
            transport=transport,
            proxy_pool=proxy_pool,
            proxy_group=proxy_group,
            relay_url=relay_url,
            management_relay_url=management_relay_url,
            relay_secret=relay_secret,
            store_slug=store_slug,
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

        if _uses_official_offer_api_only(client):
            official_payload = _normalize_official_account_payload(payload, None)
            if official_payload is None:
                return ApiResult.from_error(
                    ErrorCategory.VALIDATION,
                    'PlayerAuctions official account-offer creation requires a complete safe account payload.',
                    provider='playerauctions',
                )
            return client.create_offer(
                'account', official_payload,
                proxy_group=proxy_group,
            )

        if getattr(client, 'needs_password_encryption', True):
            payload = _encrypt_pa_passwords(payload)

        return client.create_offer(
            payload=payload,
            proxy_group=proxy_group,
        )

    def update_listing(self, client: Any, external_id: str, product_data: dict) -> Any:
        payload = product_data.get('payload', product_data)
        if _uses_official_offer_api_only(client):
            official_payload = _normalize_official_account_payload(payload, external_id)
            if official_payload is None:
                return ApiResult.from_error(
                    ErrorCategory.VALIDATION,
                    'PlayerAuctions official account-offer edit requires a complete safe account payload.',
                    provider='playerauctions',
                )
            return client.edit_offer(
                'account', official_payload,
                proxy_group=product_data.get('proxy_group'),
            )

        auto_delivery = payload.get('autoDelivery') or {}
        login_name = str(auto_delivery.get('retypeLoginName') or auto_delivery.get('loginName') or '')
        account_password = str(auto_delivery.get('retypePassword') or auto_delivery.get('password') or '')
        title = str(payload.get('title') or '')
        description = str(payload.get('offerDesc') or '')
        price = payload.get('price')
        if not login_name or not account_password:
            from apis_sdk.core.enums import ErrorCategory
            from apis_sdk.core.result import ApiResult

            return ApiResult.from_error(
                ErrorCategory.VALIDATION,
                'PlayerAuctions edit requires stored login and password confirmation fields',
                provider='playerauctions',
            )
        edit_kwargs = {
            'offer_id': int(external_id),
            'login_name': login_name,
            'account_password': account_password,
            'title': title,
            'description': description,
            'price': price,
        }
        if payload.get('isAgree') is True:
            edit_kwargs['confirm_secure_delivery_agreement'] = True
        return client.edit_offer_in_browser(**edit_kwargs)

    def delete_listing(self, client: Any, external_id: str) -> Any:
        return client.cancel_offers(
            PlayerAuctionsCancelRequest(offerIds=[int(external_id)])
        )

    def fetch_orders(self, client: Any, **kwargs) -> Any:
        return client.list_seller_orders(**kwargs)

    def fetch_order_details(self, client: Any, order_id: str) -> Any:
        """Fetch rich order detail for a single order."""
        return client.get_order_details(order_id=order_id)


def _is_official_mart_credential(credential: Any, creds: dict[str, Any]) -> bool:
    """Identify the explicitly approved Mart account without examining secrets."""
    candidates = (
        creds.get('store_slug', ''),
        getattr(getattr(credential, 'account', None), 'slug', ''),
    )
    return any(str(value or '').strip().lower() in _OFFICIAL_MART_STORE_SLUGS for value in candidates)


def _uses_official_offer_api_only(client: Any) -> bool:
    enabled = getattr(client, 'uses_official_offer_api_only', None)
    return bool(enabled()) if callable(enabled) else False


def _normalize_official_account_payload(
    payload: dict[str, Any],
    external_id: str | None,
) -> dict[str, Any] | None:
    """Build the documented full Account Offer update shape without a relay.

    The official API replaces the offer body on PUT.  Do not submit a partial
    title/price patch: retain only the validated current fields, including the
    delivery block, and reject incomplete historical payloads.
    """
    if not isinstance(payload, dict):
        return None
    try:
        game_id = int(payload.get('gameId'))
        server_id = int(payload.get('serverId'))
        category_id = int(payload.get('categoryId'))
        price = float(payload.get('price'))
        duration = int(payload.get('offerDuration', 30))
    except (TypeError, ValueError):
        return None
    protection = payload.get(
        'selleraftersaleprotection',
        payload.get('sellerAfterSaleProtection', payload.get('freeInsurance')),
    )
    try:
        protection = int(protection)
    except (TypeError, ValueError):
        return None
    title = str(payload.get('title') or '').strip()
    is_auto = payload.get('isAuto')
    offer_id: int | None = None
    if external_id is not None:
        try:
            offer_id = int(str(external_id))
        except (TypeError, ValueError):
            return None
    if (
        (offer_id is not None and offer_id <= 0)
        or game_id <= 0 or server_id <= 0 or category_id <= 0
        or price <= 0 or duration not in {3, 7, 14, 30}
        or protection not in {0, 7, 14, 30} or not title
        or not isinstance(is_auto, bool)
    ):
        return None
    normalized: dict[str, Any] = {
        'gameId': game_id,
        'serverId': server_id,
        'categoryId': category_id,
        'price': price,
        'selleraftersaleprotection': protection,
        'offerDuration': duration,
        'title': title[:150],
        'offerDesc': str(payload.get('offerDesc') or '')[:3000],
        'screenShot': str(payload.get('screenShot') or ''),
        'agreeCheck': True,
        'isAuto': is_auto,
    }
    if offer_id is not None:
        normalized['offerId'] = offer_id
    if is_auto:
        delivery = copy.deepcopy(payload.get('autoDelivery') or {})
        required = ('loginName', 'password', 'original', 'current')
        if not isinstance(delivery, dict) or any(not delivery.get(key) for key in required):
            return None
        if not isinstance(delivery.get('isInfoSame'), bool) or not isinstance(delivery.get('choose5'), bool):
            return None
        delivery['retypeLoginName'] = delivery.get('retypeLoginName') or delivery['loginName']
        delivery['retypePassword'] = delivery.get('retypePassword') or delivery['password']
        normalized['autoDelivery'] = delivery
        return normalized

    manual = copy.deepcopy(payload.get('manual') or {})
    if not isinstance(manual, dict) or not manual.get('loginName') or not manual.get('deliveryGuarantee'):
        return None
    for field in ('choose1', 'choose2', 'choose3', 'choose4', 'choose5'):
        if manual.get(field) is not True:
            return None
    manual['retypeLoginName'] = manual.get('retypeLoginName') or manual['loginName']
    normalized['manual'] = manual
    return normalized


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
