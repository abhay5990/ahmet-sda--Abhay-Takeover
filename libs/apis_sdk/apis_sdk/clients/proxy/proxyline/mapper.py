"""
Proxyline response mapper.

Translates Proxyline-specific API response models into
SDK-canonical ProxyRecord instances.
"""

from __future__ import annotations

from apis_sdk.core.enums import ProxyProtocol
from apis_sdk.core.models import ProxyRecord
from apis_sdk.clients.proxy.proxyline.models import ProxylineProxy


class ProxylineMapper:
    """Maps Proxyline API models to SDK ProxyRecord."""

    @staticmethod
    def to_proxy_record(
        proxy: ProxylineProxy,
        *,
        group: str = "",
        prefer_socks5: bool = False,
    ) -> ProxyRecord:
        """
        Map a ProxylineProxy API response to a canonical ProxyRecord.

        Args:
            proxy: Raw Proxyline API proxy entry.
            group: Group label to assign to this proxy.
            prefer_socks5: If True and socks5 port is available, use socks5.
        """
        if prefer_socks5 and proxy.port_socks5:
            protocol = ProxyProtocol.SOCKS5
            port = proxy.port_socks5
        else:
            protocol = ProxyProtocol.HTTP
            port = proxy.port_http

        return ProxyRecord(
            host=proxy.ip,
            port=port,
            protocol=protocol,
            username=proxy.user or None,
            password=proxy.password or None,
            provider="proxyline",
            group=group,
            metadata={
                "proxyline_id": proxy.id,
                "country": proxy.country,
                "type": proxy.type,
                "date_end": proxy.date_end,
            },
        )

    @staticmethod
    def to_proxy_records(
        proxies: list[ProxylineProxy],
        *,
        group: str = "",
        prefer_socks5: bool = False,
    ) -> list[ProxyRecord]:
        """Map a list of Proxyline proxies to SDK ProxyRecords."""
        return [
            ProxylineMapper.to_proxy_record(p, group=group, prefer_socks5=prefer_socks5)
            for p in proxies
            if p.is_active
        ]
