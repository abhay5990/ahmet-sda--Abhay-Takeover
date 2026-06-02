"""
Token Broker Service — DB-centric token cache with double-checked locking.

- Token valid → return from DB (zero Cognito calls)
- Token expired/missing → SELECT FOR UPDATE lock, single refresh, save to DB
- Concurrent requests: only one thread hits Cognito, others wait and get the refreshed token
- Refresh flow: REFRESH_TOKEN_AUTH first (no password), SRP as last resort
- Cognito throttle protection: cooldown period after "Password attempts exceeded"

Note: SELECT FOR UPDATE is effective on MySQL/PostgreSQL.
On SQLite (dev) it's a no-op — acceptable since dev is single-process.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.integrations.models import IntegrationAccount, IntegrationCredential

logger = logging.getLogger(__name__)

SUPPORTED_MARKETPLACES = frozenset({'eldorado'})
TOKEN_SAFETY_BUFFER = timedelta(seconds=60)
COGNITO_COOLDOWN_SECONDS = 900  # 15 min cooldown after throttle


class StoreNotFound(Exception):
    pass


class UnsupportedMarketplace(Exception):
    pass


class CognitoThrottled(Exception):
    """Raised when Cognito throttle cooldown is active."""
    def __init__(self, remaining_seconds: int):
        self.remaining_seconds = remaining_seconds
        super().__init__(f"Cognito cooldown active ({remaining_seconds}s remaining)")


class TokenBrokerService:

    def get_token(self, marketplace: str, store_slug: str) -> dict:
        if marketplace not in SUPPORTED_MARKETPLACES:
            raise UnsupportedMarketplace(f"Token broker does not support marketplace: {marketplace}")

        credential = self._get_credential(marketplace, store_slug)

        # Fast path: token still valid → return from DB
        if not self._needs_refresh(credential):
            return self._build_response(credential, marketplace, store_slug)

        # Slow path: expired/missing → lock + refresh
        _throttle_detected = False
        try:
            with transaction.atomic():
                credential = (
                    IntegrationCredential.objects
                    .select_for_update()
                    .get(pk=credential.pk)
                )
                # Double-check: another request may have refreshed while we waited
                if not self._needs_refresh(credential):
                    return self._build_response(credential, marketplace, store_slug)

                # Cooldown check: skip refresh if Cognito throttle was hit recently
                cooldown_until = credential.credentials.get('cognito_cooldown_until')
                if cooldown_until:
                    remaining = cooldown_until - timezone.now().timestamp()
                    if remaining > 0:
                        logger.warning(
                            "Token broker: Cognito cooldown active for %s/%s (%ds remaining)",
                            marketplace, store_slug, int(remaining),
                        )
                        raise CognitoThrottled(int(remaining))

                logger.info(
                    "Token broker: refreshing token for %s/%s",
                    marketplace, store_slug,
                )
                try:
                    token_data = self._refresh_token(credential, marketplace)
                except Exception as exc:
                    if self._is_cognito_throttle(exc):
                        _throttle_detected = True
                    raise

                extra = {'id_token': token_data['id_token']}
                if token_data.get('refresh_token'):
                    extra['refresh_token'] = token_data['refresh_token']
                # Clear cooldown on successful refresh
                if credential.credentials.get('cognito_cooldown_until'):
                    extra['cognito_cooldown_until'] = None
                credential.update_token(
                    access_token=token_data['id_token'],
                    expires_at=timezone.now() + timedelta(seconds=token_data['expires_in']),
                    **extra,
                )
                return self._build_response(credential, marketplace, store_slug)
        except CognitoThrottled:
            raise  # already recorded in DB, no further action
        except Exception:
            if _throttle_detected:
                # Save cooldown OUTSIDE the transaction so it isn't rolled back
                self._enter_cooldown(credential)
            raise

    def _needs_refresh(self, credential: IntegrationCredential) -> bool:
        """
        Broker-specific token validity check.

        Unlike is_token_expired which treats None expires_at as "not expired",
        this returns True for missing token or missing/past expiry.
        """
        id_token = credential.credentials.get('id_token')
        expires_at = credential.token_expires_at
        if not id_token or not expires_at:
            return True
        return timezone.now() >= (expires_at - TOKEN_SAFETY_BUFFER)

    def _get_credential(self, marketplace: str, store_slug: str) -> IntegrationCredential:
        try:
            account = IntegrationAccount.objects.get(
                provider=marketplace,
                slug=store_slug,
                is_active=True,
            )
        except IntegrationAccount.DoesNotExist:
            raise StoreNotFound(f"No active account found: {marketplace}/{store_slug}")

        try:
            credential = account.credential
        except IntegrationCredential.DoesNotExist:
            raise StoreNotFound(f"No credentials configured for: {marketplace}/{store_slug}")

        if not credential.is_active:
            raise StoreNotFound(f"Credentials are inactive for: {marketplace}/{store_slug}")

        return credential

    def _refresh_token(self, credential: IntegrationCredential, marketplace: str) -> dict:
        if marketplace == 'eldorado':
            return self._refresh_eldorado(credential)
        raise UnsupportedMarketplace(f"Token refresh not implemented for: {marketplace}")

    def _refresh_eldorado(self, credential: IntegrationCredential) -> dict:
        """Refresh Eldorado token via Cognito — tries refresh token first, then SRP."""
        from apis_sdk.clients.marketplaces.eldorado.auth import EldoradoCognitoAuth
        from apis_sdk.clients.marketplaces.eldorado.config import EldoradoConfig

        creds = credential.credentials
        config = EldoradoConfig(
            email=creds.get('email', ''),
            password=creds.get('password', ''),
            enable_cognito_auth=True,
        )
        auth = EldoradoCognitoAuth(
            config,
            initial_refresh_token=creds.get('refresh_token', ''),
        )
        auth.refresh()
        return {
            'id_token': auth.id_token,
            'expires_in': int(EldoradoCognitoAuth.TOKEN_TTL_SECONDS),
            'refresh_token': auth.refresh_token,
        }

    @staticmethod
    def _is_cognito_throttle(exc: Exception) -> bool:
        err = str(exc).lower()
        return (
            "password attempts exceeded" in err
            or "too many requests" in err
            or "throttling" in err
        )

    @staticmethod
    def _enter_cooldown(credential: IntegrationCredential) -> None:
        cooldown_until = timezone.now().timestamp() + COGNITO_COOLDOWN_SECONDS
        creds = credential.credentials.copy()
        creds['cognito_cooldown_until'] = cooldown_until
        credential.credentials = creds
        credential.save(update_fields=['credentials', 'updated_at'])
        logger.error(
            "Token broker: Cognito throttle detected, cooldown set for %ds",
            COGNITO_COOLDOWN_SECONDS,
        )

    def _build_response(self, credential: IntegrationCredential, marketplace: str, store_slug: str) -> dict:
        expires_at = credential.token_expires_at
        expires_in = (
            max(0, int((expires_at - timezone.now()).total_seconds()))
            if expires_at else 0
        )
        return {
            'token': credential.credentials.get('id_token', ''),
            'expires_in': expires_in,
            'marketplace': marketplace,
            'store': store_slug,
        }
