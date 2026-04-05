"""
Eldorado client configuration.

Holds all connection settings needed for the Eldorado API,
including authentication credentials.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class EldoradoConfig(BaseModel):
    """Configuration for the Eldorado API client."""

    email: str = Field(default="", description="Eldorado account email")
    password: str = Field(default="", description="Eldorado account password")
    base_url: str = Field(
        default="https://www.eldorado.gg",
        description="Eldorado API base URL",
    )
    timeout: float = Field(default=30.0, gt=0, description="Request timeout in seconds")
    store_identifier: str = Field(
        default="eldorado_main",
        description="Unique identifier for this store instance",
    )
    id_token: str = Field(
        default="",
        description="Optional pre-fetched Eldorado ID token.",
    )
    id_token_ttl_seconds: float = Field(
        default=3600.0,
        gt=0,
        description="TTL used when id_token is provided directly.",
    )
    enable_cognito_auth: bool = Field(
        default=False,
        description="Enable Cognito SRP authentication flow.",
    )

    # Cognito settings
    cognito_region: str = Field(
        default="us-east-2",
        description="AWS Cognito region",
    )
    cognito_user_pool_id: str = Field(
        default="us-east-2_MlnzCFgHk",
        description="AWS Cognito user pool ID",
    )
    cognito_client_id: str = Field(
        default="1956req5ro9drdtbf5i6kis4la",
        description="AWS Cognito client ID",
    )

    @model_validator(mode="after")
    def _validate_auth_shape(self) -> "EldoradoConfig":
        """
        Validate auth config shape.

        Cognito mode requires email and password. Token mode can run with id_token.
        """
        if self.enable_cognito_auth and (not self.email or not self.password):
            raise ValueError(
                "EldoradoConfig requires email and password when enable_cognito_auth=True.",
            )
        return self

    model_config = {"frozen": True}
