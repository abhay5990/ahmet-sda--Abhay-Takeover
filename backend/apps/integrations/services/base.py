from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ServiceField:
    """Describes a single credential field for a utility service.

    Used by Django Admin to render service-specific forms dynamically.
    Mirrors CredentialField in providers/base.py but without marketplace coupling.
    """
    name:       str
    label:      str
    field_type: str = 'text'   # text, password, url, readonly
    required:   bool = True
    help_text:  str = ''


class AbstractServiceDefinition(ABC):
    """Base class for all utility service definitions.

    Each external service (Proxyline, Imgur, Dropbox, RobuxCrate, etc.)
    subclasses this and declares its credential fields.

    Unlike AbstractProvider, there are NO marketplace operations here
    (no fetch_orders, create_listing, etc.). Services only define:
      - What credentials they need (get_fields)
      - Optionally, how to build a client (build_client)

    Usage:
        @register_service
        class ProxylineService(AbstractServiceDefinition):
            service_type = 'proxy'

            @classmethod
            def get_fields(cls) -> list[ServiceField]:
                return [
                    ServiceField('api_key', 'API Key', 'password'),
                ]
    """

    service_type: str = ''    # Must match a ServiceType value in models.py
    display_name: str = ''    # Human-readable name (optional, for admin)

    @classmethod
    @abstractmethod
    def get_fields(cls) -> list[ServiceField]:
        """Return the list of credential fields this service requires."""
        ...

    @classmethod
    def validate_credentials(cls, credentials: dict) -> list[str]:
        """Validate that required fields are present. Returns list of error strings."""
        errors = []
        for f in cls.get_fields():
            if f.required and not credentials.get(f.name):
                errors.append(f"{f.label} is required.")
        return errors

    @classmethod
    def test_connection(cls, client) -> tuple[bool, str]:
        """Test connectivity with the built client.

        Returns (success, message). Subclasses override for service-specific checks.
        Default: no test available.
        """
        return False, "Connection test not implemented for this service."
