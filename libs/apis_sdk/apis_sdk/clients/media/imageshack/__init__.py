"""
ImageShack image hosting client.

Modules:
- config  — connection settings
- client  — low-level API client
- facade  — high-level consumer-facing API
"""

from apis_sdk.clients.media.imageshack.facade import ImageShackFacade

__all__ = ["ImageShackFacade"]
