from __future__ import annotations

from typing import TYPE_CHECKING

from .base import AbstractServiceDefinition, ServiceField

if TYPE_CHECKING:
    pass

_services: dict[str, AbstractServiceDefinition] = {}
_fully_loaded: bool = False


def register_service(cls: type[AbstractServiceDefinition]) -> type[AbstractServiceDefinition]:
    """Class decorator that registers a service definition in the registry.

    Usage:
        @register_service
        class ProxylineService(AbstractServiceDefinition):
            service_type = 'proxy'
            ...
    """
    if not cls.service_type:
        raise ValueError(f"{cls.__name__} must define service_type")
    _services[cls.service_type] = cls()
    return cls


def get_service(service_type: str) -> AbstractServiceDefinition | None:
    """Return the service definition instance for a given service_type, or None."""
    _ensure_loaded()
    return _services.get(service_type)


def get_service_fields(service_type: str) -> list[ServiceField]:
    """Return credential fields for a given service_type. Empty list if unknown."""
    _ensure_loaded()
    svc = _services.get(service_type)
    if svc is None:
        return []
    return svc.get_fields()


def _ensure_loaded():
    """Lazily import all service modules so their @register_service decorators run."""
    global _fully_loaded
    if _fully_loaded:
        return
    from . import dropbox, firstmail, google_sheets, imageshack, imgur, proxyline, robuxcrate, telegram  # noqa: F401 — trigger registration
    _fully_loaded = True
