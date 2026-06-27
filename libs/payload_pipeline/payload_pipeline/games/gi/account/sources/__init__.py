"""Prepared source adapters for Genshin Impact."""

from .lzt import GenshinLztSourceAdapter
from .manual import GiManualSourceAdapter

__all__ = ["GenshinLztSourceAdapter", "GiManualSourceAdapter"]
