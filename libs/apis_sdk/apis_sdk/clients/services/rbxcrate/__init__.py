"""
RBXCrate Robux delivery service client.

Modules:
- config     — connection settings
- endpoints  — API URL constants
- client     — low-level API client
- facade     — high-level consumer-facing API
"""

from apis_sdk.clients.services.rbxcrate.facade import RbxCrateFacade

__all__ = ["RbxCrateFacade"]
