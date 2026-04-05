from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from apis_sdk.factories.transport_factory import TransportFactory

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationCredential


@dataclass
class CredentialField:
    """Describes a single credential field for a provider.

    Used by Django Admin to render provider-specific forms dynamically.
    """
    name: str
    label: str
    field_type: str = 'text'  # text, password, readonly
    required: bool = True
    help_text: str = ''
    read_only: bool = False


class AbstractProvider(ABC):
    """Base interface for all marketplace provider integrations.

    Each provider (LZT, G2G, Eldorado, Gameboost) implements this interface.
    Providers wrap apis_sdk facades and handle credential-to-client construction.
    """

    provider_name: str = ''
    display_name: str = ''

    @classmethod
    def get_credential_fields(cls) -> list[CredentialField]:
        """Define which credential fields this provider needs.

        Override in each provider. Used by Admin to render the right form fields.
        Default: single api_key field.
        """
        return [
            CredentialField('api_key', 'API Key', field_type='password'),
        ]

    @classmethod
    def validate_credentials(cls, credentials: dict) -> list[str]:
        """Validate that required credential fields are present. Returns list of errors."""
        errors = []
        for field in cls.get_credential_fields():
            if field.required and not credentials.get(field.name):
                errors.append(f"{field.label} is required.")
        return errors

    @abstractmethod
    def build_client(
        self,
        credential: IntegrationCredential,
        *,
        proxy_pool: Any | None = None,
        proxy_group: str | None = None,
    ) -> Any:
        """Build an SDK facade instance from DB-backed credentials.

        This is the key integration point: reads credential data from the
        IntegrationCredential model and passes it to the appropriate SDK factory.

        proxy_pool: SDK ProxyPool instance for group-based proxy rotation.
        proxy_group: AccountGroup name to filter proxies in the pool.
        """
        ...

    def _create_transport(self, timeout: float = 30.0):
        """Create a default HTTP transport via SDK factory."""
        return TransportFactory.create_requests_transport(timeout=timeout)

    @abstractmethod
    def fetch_products(self, client: Any, **kwargs) -> Any:
        """Fetch products/listings from the marketplace."""
        ...

    @abstractmethod
    def create_listing(self, client: Any, product_data: dict) -> Any:
        """Create a new listing on the marketplace."""
        ...

    @abstractmethod
    def update_listing(self, client: Any, external_id: str, product_data: dict) -> Any:
        """Update an existing listing."""
        ...

    @abstractmethod
    def delete_listing(self, client: Any, external_id: str) -> Any:
        """Remove a listing from the marketplace."""
        ...

    @abstractmethod
    def fetch_orders(self, client: Any, **kwargs) -> Any:
        """Fetch orders/sales from the marketplace."""
        ...

    def fetch_order_account_details(self, client: Any, order_id: str) -> dict | None:
        """Fetch account delivery details for a specific order.

        Only relevant for providers that sell account-type products with
        instant delivery. Returns the account details dict or None if
        not supported by this provider.
        """
        return None

    def get_listing_url(self, external_id: str) -> str | None:
        """Get public URL for a listing. Override in subclass."""
        return None
