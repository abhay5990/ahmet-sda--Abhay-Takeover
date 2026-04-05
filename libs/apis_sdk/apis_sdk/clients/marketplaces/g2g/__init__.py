"""
G2G marketplace client.

Modules:
- config     — connection settings and credential fields
- endpoints  — API URL constants
- models     — API response models and envelope structure
- exceptions — provider-specific errors
- auth       — reactive token refresh provider
- client     — low-level API client with envelope unwrapping
- facade     — high-level consumer-facing API with throttling
"""

from apis_sdk.clients.marketplaces.g2g.facade import G2GFacade

__all__ = ["G2GFacade"]
