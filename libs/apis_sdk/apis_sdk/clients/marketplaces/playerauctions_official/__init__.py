"""
PlayerAuctions Official Seller API client package.

Uses the official PA Seller API (seller-api.playerauctions.com) with
HMAC-SHA256 authentication. This is separate from the legacy
``playerauctions`` package which uses browser-based JWT auth.
"""

from apis_sdk.clients.marketplaces.playerauctions_official.auth import PAOfficialAuth
from apis_sdk.clients.marketplaces.playerauctions_official.client import PAOfficialClient
from apis_sdk.clients.marketplaces.playerauctions_official.config import PAOfficialConfig
from apis_sdk.clients.marketplaces.playerauctions_official.endpoints import PAOfficialEndpoints
from apis_sdk.clients.marketplaces.playerauctions_official.facade import PAOfficialFacade

__all__ = [
    "PAOfficialAuth",
    "PAOfficialClient",
    "PAOfficialConfig",
    "PAOfficialEndpoints",
    "PAOfficialFacade",
]
