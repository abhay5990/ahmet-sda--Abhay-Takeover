"""
SDK logging abstraction.

Provides a thin logging interface that the SDK uses internally.
Consumers inject their preferred logger implementation (stdlib logging,
structlog, loguru, etc.) without the SDK depending on any of them.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any


class SdkLogger(ABC):
    """Abstract logger interface for the SDK."""

    @abstractmethod
    def debug(self, message: str, **kwargs: Any) -> None: ...

    @abstractmethod
    def info(self, message: str, **kwargs: Any) -> None: ...

    @abstractmethod
    def warning(self, message: str, **kwargs: Any) -> None: ...

    @abstractmethod
    def error(self, message: str, **kwargs: Any) -> None: ...


class NullLogger(SdkLogger):
    """Logger that discards all messages. Used as default when no logger is configured."""

    def debug(self, message: str, **kwargs: Any) -> None:
        pass

    def info(self, message: str, **kwargs: Any) -> None:
        pass

    def warning(self, message: str, **kwargs: Any) -> None:
        pass

    def error(self, message: str, **kwargs: Any) -> None:
        pass


class StdlibLogger(SdkLogger):
    """Adapter that delegates to Python's standard logging module."""

    def __init__(self, name: str = "apis_sdk") -> None:
        self._logger = logging.getLogger(name)

    def debug(self, message: str, **kwargs: Any) -> None:
        self._logger.debug(message, extra=kwargs)

    def info(self, message: str, **kwargs: Any) -> None:
        self._logger.info(message, extra=kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self._logger.warning(message, extra=kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self._logger.error(message, extra=kwargs)
