"""
Proxyline API response models.

These represent the raw API responses from Proxyline.
They are mapped to SDK-canonical ProxyRecord via the mapper module.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProxylineProxy(BaseModel):
    """A single proxy entry from the Proxyline API response."""

    id: int
    ip: str
    port_http: int
    port_socks5: int | None = None
    user: str = ""
    password: str = ""
    type: str = ""
    country: str = ""
    date_end: str = ""
    is_active: bool = True

    model_config = {"frozen": True}


class ProxylineListResponse(BaseModel):
    """Paginated list response from Proxyline API."""

    count: int = 0
    results: list[ProxylineProxy] = Field(default_factory=list)


class ProxylineBalance(BaseModel):
    """Balance response from Proxyline API."""

    balance: float = 0.0
    currency: str = "USD"


class ProxylineOrder(BaseModel):
    """An order/subscription entry from the Proxyline API."""

    id: int
    proxy_count: int = 0
    period: int = 0
    country: str = ""
    status: str = ""
    date_end: str = ""

    model_config = {"frozen": True}
