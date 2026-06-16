"""New World game slice (account + item)."""

from .account import register as register_account
from .item import register as register_item


def register(registry) -> None:
    register_account(registry)
    register_item(registry)


__all__ = ["register"]
