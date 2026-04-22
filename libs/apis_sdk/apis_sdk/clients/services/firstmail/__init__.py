"""
FirstMail email service client.

Modules:
- config    — connection settings
- models    — API response models
- endpoints — URL constants
- client    — low-level API client
- facade    — high-level consumer-facing API
"""

from apis_sdk.clients.services.firstmail.facade import FirstMailFacade

__all__ = ["FirstMailFacade"]
