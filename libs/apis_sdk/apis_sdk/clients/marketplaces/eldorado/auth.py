"""
Eldorado authentication provider.

Supports two modes:
1. Pre-fetched token mode via EldoradoConfig.id_token
2. Optional Cognito SRP flow when enable_cognito_auth=True
"""

from __future__ import annotations

import time

from apis_sdk.core.exceptions import AuthenticationError
from apis_sdk.infrastructure.auth.base import BaseAuthProvider
from apis_sdk.infrastructure.logging.logger import NullLogger, SdkLogger
from apis_sdk.clients.marketplaces.eldorado.config import EldoradoConfig
from apis_sdk.clients.marketplaces.eldorado.exceptions import (
    EldoradoProviderNotReadyError,
)


class EldoradoCognitoAuth(BaseAuthProvider):
    """
    Eldorado authentication provider.

    Manages the ID token lifecycle:
    - Uses pre-fetched token when provided
    - Optional SRP authentication via Cognito
    - Token refresh before expiry
    - Thread-safe access to auth headers
    """

    TOKEN_TTL_SECONDS = 3600.0

    def __init__(
        self,
        config: EldoradoConfig,
        *,
        logger: SdkLogger | None = None,
        initial_refresh_token: str = "",
    ) -> None:
        super().__init__()
        self._config = config
        self._logger = logger or NullLogger()
        self._id_token: str = ""
        self._access_token: str = ""
        self._refresh_token: str = initial_refresh_token
        if self._config.id_token:
            self.set_id_token(
                self._config.id_token,
                ttl=self._config.id_token_ttl_seconds,
            )

    @property
    def id_token(self) -> str:
        return self._id_token

    def set_id_token(self, token: str, *, ttl: float | None = None) -> None:
        """Set token directly (used for pre-fetched token mode)."""
        self._id_token = token
        effective_ttl = ttl if ttl is not None else self.TOKEN_TTL_SECONDS
        self._expires_at = time.monotonic() + max(60.0, effective_ttl)

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    def _do_refresh(self) -> bool:
        """
        Refresh token — tries REFRESH_TOKEN_AUTH first, falls back to SRP.

        REFRESH_TOKEN_AUTH does not require a password, so it avoids
        Cognito's "Password attempts exceeded" throttle entirely.
        Refresh tokens are valid for 30 days (Cognito default).
        """
        if not self._config.enable_cognito_auth:
            raise EldoradoProviderNotReadyError(
                "Eldorado auth is not ready for automatic login. "
                "Provide `id_token` in EldoradoConfig for pilot usage, or "
                "enable Cognito auth explicitly with `enable_cognito_auth=True`."
            )

        try:
            import boto3
        except ImportError as exc:
            raise EldoradoProviderNotReadyError(
                "Cognito auth requires optional dependency `boto3`."
            ) from exc

        if not self._config.email or not self._config.password:
            raise AuthenticationError(
                "Missing Eldorado credentials for Cognito authentication.",
                provider="eldorado",
            )

        cognito = boto3.client(
            "cognito-idp",
            region_name=self._config.cognito_region,
        )

        # 1) Try REFRESH_TOKEN_AUTH first (no password, no throttle risk)
        if self._refresh_token:
            refreshed = self._try_refresh_token_auth(cognito)
            if refreshed:
                return True
            # refresh failed → fall through to SRP

        # 2) Fall back to SRP (full password login)
        return self._srp_login(cognito)

    def _try_refresh_token_auth(self, cognito) -> bool:
        """Attempt Cognito REFRESH_TOKEN_AUTH. Returns True on success."""
        self._logger.info(
            "Eldorado refresh token auth attempt (no SRP)",
            store=self._config.store_identifier,
        )
        try:
            resp = cognito.initiate_auth(
                AuthFlow="REFRESH_TOKEN_AUTH",
                AuthParameters={"REFRESH_TOKEN": self._refresh_token},
                ClientId=self._config.cognito_client_id,
            )
            result = resp.get("AuthenticationResult") or {}
            id_token = str(result.get("IdToken", ""))
            if not id_token:
                self._logger.warning(
                    "Refresh response missing IdToken, falling back to SRP",
                    store=self._config.store_identifier,
                )
                return False

            self._id_token = id_token
            self._access_token = str(result.get("AccessToken", ""))
            # Cognito pool rotation OFF → response may not include new refresh token
            new_refresh = result.get("RefreshToken")
            if new_refresh:
                self._refresh_token = str(new_refresh)
            expires_in = float(result.get("ExpiresIn", self.TOKEN_TTL_SECONDS))
            self._expires_at = time.monotonic() + max(60.0, expires_in)

            self._logger.info(
                "Eldorado refresh token auth succeeded (no SRP needed)",
                store=self._config.store_identifier,
                expires_in=int(expires_in),
            )
            return True

        except Exception as exc:
            err_lower = str(exc).lower()
            if "expired" in err_lower or "notauthorizedexception" in err_lower:
                # Refresh token expired/revoked → clear it, SRP will get a new one
                self._logger.warning(
                    "Refresh token expired/revoked, falling back to SRP",
                    store=self._config.store_identifier,
                    error=str(exc)[:120],
                )
                self._refresh_token = ""
            else:
                self._logger.warning(
                    "Refresh token auth failed unexpectedly, falling back to SRP",
                    store=self._config.store_identifier,
                    error=str(exc)[:120],
                )
            return False

    def _srp_login(self, cognito) -> bool:
        """Full SRP login (password-based). Last resort after refresh fails."""
        self._logger.info(
            "Eldorado Cognito SRP auth requested",
            store=self._config.store_identifier,
        )

        try:
            from pycognito import AWSSRP
        except ImportError as exc:
            raise EldoradoProviderNotReadyError(
                "Cognito SRP auth requires optional dependency `pycognito`."
            ) from exc

        try:
            aws_srp = AWSSRP(
                username=self._config.email,
                password=self._config.password,
                pool_id=self._config.cognito_user_pool_id,
                client_id=self._config.cognito_client_id,
                client=cognito,
            )
            params = aws_srp.get_auth_params()
            challenge_response = cognito.initiate_auth(
                AuthFlow="USER_SRP_AUTH",
                AuthParameters=params,
                ClientId=self._config.cognito_client_id,
            )
            challenge_name = challenge_response.get("ChallengeName")
            if challenge_name != "PASSWORD_VERIFIER":
                raise AuthenticationError(
                    f"Unexpected Cognito challenge: {challenge_name}",
                    provider="eldorado",
                )

            challenge = aws_srp.process_challenge(
                challenge_response["ChallengeParameters"],
                params,
            )
            auth_response = cognito.respond_to_auth_challenge(
                ClientId=self._config.cognito_client_id,
                ChallengeName="PASSWORD_VERIFIER",
                ChallengeResponses=challenge,
            )

            auth_result = auth_response.get("AuthenticationResult", {})
            id_token = str(auth_result.get("IdToken", ""))
            if not id_token:
                raise AuthenticationError(
                    "Cognito response did not include IdToken.",
                    provider="eldorado",
                )

            self._id_token = id_token
            self._access_token = str(auth_result.get("AccessToken", ""))
            self._refresh_token = str(
                auth_result.get("RefreshToken", self._refresh_token),
            )
            expires_in = float(auth_result.get("ExpiresIn", self.TOKEN_TTL_SECONDS))
            self._expires_at = time.monotonic() + max(60.0, expires_in)
            return True
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError(
                f"Eldorado Cognito authentication failed: {exc}",
                provider="eldorado",
            ) from exc

    def _build_headers(self) -> dict[str, str]:
        """Build Eldorado auth headers using the Cognito ID token."""
        if not self._id_token:
            return {}
        return {
            "Cookie": f"__Host-EldoradoIdToken={self._id_token}",
        }
