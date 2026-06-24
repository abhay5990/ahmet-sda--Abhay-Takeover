"""
Roblox public API client.

Modules:
- config     — connection settings (incl. proxy)
- endpoints  — API URL constants
- client     — low-level API client
- facade     — high-level consumer-facing API with pagination
"""

from apis_sdk.clients.services.roblox.facade import RobloxFacade

__all__ = ["RobloxFacade"]
