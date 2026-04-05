"""
Proxy runtime engine — pool management, rotation, health tracking, selection.

This is the *infrastructure* side of proxies: it manages a pool of proxy entries
at runtime. The proxy *providers* (Proxyline, DataImpulse) that fetch proxy lists
from external APIs live in clients/proxy/.
"""

from apis_sdk.infrastructure.proxy.pool import ProxyPool
from apis_sdk.infrastructure.proxy.rotation import RotationStrategy, RoundRobinRotation, RandomRotation
from apis_sdk.infrastructure.proxy.health import ProxyHealthTracker

__all__ = [
    "ProxyPool",
    "RotationStrategy",
    "RoundRobinRotation",
    "RandomRotation",
    "ProxyHealthTracker",
]
