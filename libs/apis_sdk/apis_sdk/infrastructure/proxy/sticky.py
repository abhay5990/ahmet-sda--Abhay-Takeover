"""Sticky residential proxy with a rotatable session id.

DataImpulse (and similar residential providers) pin the exit IP to a
"session id" embedded in the proxy username: appending ``;sessid.<id>`` keeps
the same exit IP for as long as that id is used. Generating a new id yields a
fresh exit IP — used to escape IP bans / rate limits and for proactive
rotation after a request budget is spent.

Unlike :class:`ProxyPool` (many distinct proxies, round-robin + health), this
wraps a SINGLE upstream credential whose exit IP is steered via the session id.
Both the browser (Cloudflare solve) and the curl request must use the SAME
sticky proxy so the cf_clearance cookie — which Cloudflare binds to the exit
IP — stays valid. Rotating therefore invalidates the current cookie; callers
must pair :meth:`rotate` with a cookie re-solve.
"""

from __future__ import annotations

import threading
import uuid

from apis_sdk.core.enums import ProxyProtocol
from apis_sdk.core.models import ProxyRecord

_SESSID_TAG = "sessid"  # DataImpulse sticky-session marker in the username


def _new_sessid() -> str:
    """A fresh, opaque sticky-session id (-> fresh exit IP)."""
    return uuid.uuid4().hex[:12]


class StickyResidentialProxy:
    """A single residential proxy with a rotatable sticky-session id.

    Thread-safe. The exit IP stays constant while the session id is unchanged
    (same id -> same IP) and changes on :meth:`rotate`.

    Usage:
        proxy = StickyResidentialProxy.from_record(db_proxy_record)
        url = proxy.proxy_url          # browser + curl both use this -> same IP
        ...
        proxy.rotate()                 # ban/budget -> new exit IP (re-solve!)
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        protocol: ProxyProtocol = ProxyProtocol.HTTP,
        sessid_tag: str = _SESSID_TAG,
        sessid: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._username_base = username
        self._password = password
        self._protocol = protocol
        self._sessid_tag = sessid_tag
        self._lock = threading.Lock()
        self._sessid = sessid or _new_sessid()

    @classmethod
    def from_record(
        cls, record: ProxyRecord, *, sessid: str | None = None
    ) -> "StickyResidentialProxy":
        """Build from a :class:`ProxyRecord` (e.g. loaded from the DB)."""
        if not record.username or not record.password:
            raise ValueError(
                "StickyResidentialProxy requires a username and password"
            )
        return cls(
            host=record.host,
            port=record.port,
            username=record.username,
            password=record.password,
            protocol=record.protocol,
            sessid=sessid,
        )

    # -- current identity ---------------------------------------------------

    @property
    def sessid(self) -> str:
        """The current sticky-session id (pins the exit IP)."""
        with self._lock:
            return self._sessid

    @property
    def username(self) -> str:
        """Full proxy username including the current sticky-session tag."""
        with self._lock:
            return f"{self._username_base};{self._sessid_tag}.{self._sessid}"

    @property
    def proxy_url(self) -> str:
        """Proxy URL bound to the current exit IP (via the session id).

        Both the browser and the curl transport use this; identical url ->
        identical exit IP.
        """
        with self._lock:
            user = f"{self._username_base};{self._sessid_tag}.{self._sessid}"
        return f"{self._protocol.value}://{user}:{self._password}@{self._host}:{self._port}"

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def password(self) -> str:
        return self._password

    # -- rotation -----------------------------------------------------------

    def rotate(self) -> str:
        """Switch to a fresh exit IP by generating a new session id.

        The previously minted cf_clearance is bound to the old IP and becomes
        invalid — the caller MUST re-solve the Cloudflare challenge after this.

        Returns the new session id.
        """
        with self._lock:
            self._sessid = _new_sessid()
            return self._sessid

    def __repr__(self) -> str:  # password masked for safe logging
        return (
            f"StickyResidentialProxy({self._host}:{self._port} "
            f"user={self._username_base};{self._sessid_tag}.{self.sessid})"
        )
