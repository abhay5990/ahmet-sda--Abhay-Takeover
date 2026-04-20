"""Dropship posting services — scheduler-driven poster + cleaner loops."""

from apps.posting.services.dropship.poster import poster_loop
from apps.posting.services.dropship.cleaner import cleaner_loop
from apps.posting.services.dropship.scheduler import DropshipScheduler
from apps.posting.services.dropship.source_provider import (  # noqa: F401
    DropshipSourceProvider,
    get_source_provider,
    register_source,
)

# Ensure all source providers are registered
import apps.posting.services.dropship.sources  # noqa: F401

__all__ = [
    'poster_loop', 'cleaner_loop', 'DropshipScheduler',
    'DropshipSourceProvider', 'get_source_provider', 'register_source',
]
