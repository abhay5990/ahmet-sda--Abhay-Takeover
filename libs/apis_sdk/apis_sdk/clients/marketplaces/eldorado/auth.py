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
    ) -> None:
        super().__init__()
        self._config = config
        self._logger = logger or NullLogger()
        self._id_token: str = ""
        self._access_token: str = ""
        self._refresh_token: str = ""
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

    def _do_refresh(self) -> bool:
        """
        Refresh token using Cognito SRP when enabled.

        If Cognito flow is not enabled, this raises an explicit not-ready
        exception so the provider does not appear operational by accident.
        """
        if not self._config.enable_cognito_auth:
            raise EldoradoProviderNotReadyError(
                "Eldorado auth is not ready for automatic login. "
                "Provide `id_token` in EldoradoConfig for pilot usage, or "
                "enable Cognito auth explicitly with `enable_cognito_auth=True`."
            )

        try:
            import boto3
            from pycognito import AWSSRP
        except ImportError as exc:
            raise EldoradoProviderNotReadyError(
                "Cognito auth requires optional dependencies `boto3` and `pycognito`."
            ) from exc

        if not self._config.email or not self._config.password:
            raise AuthenticationError(
                "Missing Eldorado credentials for Cognito authentication.",
                provider="eldorado",
            )

        self._logger.info(
            "Eldorado Cognito auth refresh requested",
            store=self._config.store_identifier,
        )

        try:
            cognito = boto3.client(
                "cognito-idp",
                region_name=self._config.cognito_region,
            )
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
