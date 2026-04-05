"""
Imgur image hosting client.

Modules:
- config     — connection settings
- endpoints  — API URL constants
- client     — low-level API client
- facade     — high-level consumer-facing API
"""

from apis_sdk.clients.media.imgur.facade import ImgurFacade

__all__ = ["ImgurFacade"]
