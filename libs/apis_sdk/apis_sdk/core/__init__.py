"""
Core layer — shared abstractions, protocols, result types, and exceptions.

This layer has zero external dependencies beyond the standard library and pydantic.
No provider-specific logic. No HTTP implementation. No proxy rotation.
"""

from apis_sdk.core.result import ApiResult, ErrorDetail
from apis_sdk.core.exceptions import (
    SdkError,
    TransportError,
    AuthenticationError,
    RateLimitError,
    ValidationError,
    ProviderError,
    TimeoutError,
)
from apis_sdk.core.enums import (
    ErrorCategory,
    HttpMethod,
    Platform,
    ProxyProtocol,
    ProxyStatus,
    RetryAction,
)

__all__ = [
    # Result
    "ApiResult",
    "ErrorDetail",
    # Exceptions
    "SdkError",
    "TransportError",
    "AuthenticationError",
    "RateLimitError",
    "ValidationError",
    "ProviderError",
    "TimeoutError",
    # Enums
    "ErrorCategory",
    "HttpMethod",
    "Platform",
    "ProxyProtocol",
    "ProxyStatus",
    "RetryAction",
]
