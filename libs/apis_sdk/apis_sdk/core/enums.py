"""
Shared enumerations used across the SDK.

These are domain-agnostic enums for transport, proxy, and platform concepts.
Provider-specific enums should live in their respective client modules.
"""

from enum import Enum


class HttpMethod(str, Enum):
    """Standard HTTP methods."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class ErrorCategory(str, Enum):
    """
    Categorized error types for uniform error handling across providers.

    Every provider maps its raw errors into one of these categories
    so callers can handle errors consistently regardless of provider.
    """

    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    SERVER_ERROR = "server_error"
    NETWORK = "network"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class Platform(str, Enum):
    """Supported marketplace platforms."""

    ELDORADO = "eldorado"
    GAMEBOOST = "gameboost"
    PLAYERAUCTIONS = "playerauctions"
    G2G = "g2g"


class ProxyProtocol(str, Enum):
    """Proxy connection protocols."""

    HTTP = "http"
    HTTPS = "https"
    SOCKS5 = "socks5"


class ProxyStatus(str, Enum):
    """Health status of a proxy in the pool."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    COOLDOWN = "cooldown"


class RetryAction(str, Enum):
    """
    What to do when a retry is attempted.

    Retry policies classify errors and decide *whether* to retry.
    RetryAction decides *how* — what runtime preparation is needed
    before the next attempt.
    """

    NO_RETRY = "no_retry"
    RETRY_SAME = "retry_same"
    RETRY_NEW_SESSION = "retry_new_session"
    RETRY_NEW_PROXY_AND_SESSION = "retry_new_proxy_and_session"
    REFRESH_AUTH_AND_RETRY = "refresh_auth_and_retry"
