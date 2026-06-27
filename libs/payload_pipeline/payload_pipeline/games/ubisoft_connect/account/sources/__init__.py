"""Prepared source adapters for Ubisoft Connect."""

from .lzt import UbisoftLztSourceAdapter
from .manual import UbisoftConnectManualSource, UbisoftConnectManualSourceAdapter

__all__ = ["UbisoftLztSourceAdapter", "UbisoftConnectManualSource", "UbisoftConnectManualSourceAdapter"]
