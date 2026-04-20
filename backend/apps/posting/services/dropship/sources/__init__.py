"""Dropship source platform implementations.

Each module registers its provider on import.
Import this package to ensure all providers are registered.
"""

from apps.posting.services.dropship.sources import lzt  # noqa: F401
