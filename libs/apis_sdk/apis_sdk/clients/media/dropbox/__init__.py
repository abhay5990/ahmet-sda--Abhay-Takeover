"""
Dropbox cloud storage client.

Modules:
- config     — connection settings
- endpoints  — API URL constants
- client     — low-level API client
- facade     — high-level consumer-facing API
"""

from apis_sdk.clients.media.dropbox.facade import DropboxFacade

__all__ = ["DropboxFacade"]
