"""Prepared source adapters for League of Legends."""

from .lzt import LolLztSourceAdapter
from .manual import LolManualSourceAdapter

__all__ = ["LolLztSourceAdapter", "LolManualSourceAdapter"]
