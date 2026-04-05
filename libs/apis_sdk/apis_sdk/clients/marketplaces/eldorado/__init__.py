"""
Eldorado.gg marketplace client.

Modules:
- config     — connection settings and credentials
- endpoints  — API URL constants
- models     — API request/response models
- exceptions — provider-specific errors
- mapper     — map API responses to SDK types
- auth       — Cognito SRP authentication
- client     — low-level API client
- facade     — high-level consumer-facing API
"""

from apis_sdk.clients.marketplaces.eldorado.facade import EldoradoFacade

__all__ = ["EldoradoFacade"]
