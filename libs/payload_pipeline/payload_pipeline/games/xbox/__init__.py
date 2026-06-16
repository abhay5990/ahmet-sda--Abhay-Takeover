"""Xbox game slice."""

from .account import register as register_account


def register(registry) -> None:
    register_account(registry)


__all__ = ["register"]
