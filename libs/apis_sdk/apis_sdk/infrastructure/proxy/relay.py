"""Local auth-injecting proxy relay for driving Chrome through an
authenticated upstream proxy.

Chrome's ``--proxy-server`` flag ignores ``user:pass`` credentials and modern
Chrome (150+) killed the MV2 auth-extension workaround, so a browser cannot
authenticate to a residential proxy directly. This relay bridges the gap:

    Chrome (auth-free)  ->  LocalProxyRelay 127.0.0.1:<ephemeral>
                        ->  (injects Proxy-Authorization)  ->  upstream proxy

curl_cffi does NOT need this — it accepts ``user:pass`` in the proxy URL
directly. The relay is only for the browser side of a Cloudflare solve.

Lifecycle: create one relay per solve (after any :meth:`StickyResidentialProxy.rotate`),
start it, point Chrome at :attr:`url`, stop it when the browser closes. It binds
an ephemeral localhost port (port 0 -> OS-assigned) so concurrent/repeated
solves never clash on a fixed port.
"""

from __future__ import annotations

import asyncio
import base64

from apis_sdk.infrastructure.proxy.sticky import StickyResidentialProxy

_CHUNK = 65536


class LocalProxyRelay:
    """Authless localhost HTTP proxy that chains to an authenticated upstream.

    Usage (async)::

        relay = LocalProxyRelay.for_proxy(sticky_proxy)
        url = await relay.start()                 # http://127.0.0.1:<port>
        # ... launch Chrome with --proxy-server=url, solve Cloudflare ...
        await relay.stop()

    or as an async context manager::

        async with LocalProxyRelay.for_proxy(sticky_proxy) as url:
            ...
    """

    def __init__(
        self,
        upstream_host: str,
        upstream_port: int,
        auth_b64: str,
        *,
        host: str = "127.0.0.1",
    ) -> None:
        self._up_host = upstream_host
        self._up_port = upstream_port
        self._auth_b64 = auth_b64
        self._host = host
        self._server: asyncio.AbstractServer | None = None
        self._port: int | None = None

    @classmethod
    def for_proxy(
        cls, proxy: StickyResidentialProxy, *, host: str = "127.0.0.1"
    ) -> "LocalProxyRelay":
        """Build a relay for a sticky proxy's CURRENT credentials.

        Captures the username (including the current ``;sessid.<id>``) at
        construction time, so create the relay AFTER any ``rotate()`` call.
        """
        auth = base64.b64encode(
            f"{proxy.username}:{proxy.password}".encode()
        ).decode()
        return cls(proxy.host, proxy.port, auth, host=host)

    # -- lifecycle ----------------------------------------------------------

    @property
    def url(self) -> str:
        """The ``http://host:port`` Chrome should use as its proxy."""
        if self._port is None:
            raise RuntimeError("relay not started")
        return f"http://{self._host}:{self._port}"

    async def start(self) -> str:
        """Bind an ephemeral localhost port and begin serving. Returns url."""
        self._server = await asyncio.start_server(self._handle, self._host, 0)
        self._port = self._server.sockets[0].getsockname()[1]
        return self.url

    async def stop(self) -> None:
        """Stop serving and release the port."""
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            self._server = None
            self._port = None

    async def __aenter__(self) -> str:
        return await self.start()

    async def __aexit__(self, *_exc) -> None:
        await self.stop()

    # -- internals ----------------------------------------------------------

    async def _handle(
        self, client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter
    ) -> None:
        up_w = None
        try:
            # Chrome's request line + headers (CONNECT for https, GET for http).
            header = await client_r.readuntil(b"\r\n\r\n")
            up_r, up_w = await asyncio.open_connection(self._up_host, self._up_port)
            # Inject Proxy-Authorization before the terminating blank line.
            injected = (
                header[:-2]
                + b"Proxy-Authorization: Basic "
                + self._auth_b64.encode()
                + b"\r\n\r\n"
            )
            up_w.write(injected)
            await up_w.drain()
            # Two-way tunnel: Chrome <-> upstream.
            await asyncio.gather(
                self._pipe(client_r, up_w),
                self._pipe(up_r, client_w),
            )
        except Exception:  # noqa: BLE001
            self._safe_close(client_w)
            if up_w is not None:
                self._safe_close(up_w)

    @staticmethod
    async def _pipe(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                data = await reader.read(_CHUNK)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except Exception:  # noqa: BLE001
            pass
        finally:
            LocalProxyRelay._safe_close(writer)

    @staticmethod
    def _safe_close(writer: asyncio.StreamWriter) -> None:
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass
