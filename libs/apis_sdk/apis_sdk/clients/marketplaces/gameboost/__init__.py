"""
GameBoost marketplace client.

Modules:
- config     — connection settings
- endpoints  — API URL constants
- models     — API response models
- exceptions — provider-specific errors
- mapper     — output-side response extraction
- client     — low-level API client
- facade     — high-level consumer-facing API
"""

from apis_sdk.clients.marketplaces.gameboost.facade import GameBoostFacade

__all__ = ["GameBoostFacade"]
