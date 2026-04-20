"""Clash of Clans slices for payload_pipeline."""

from .account import register as register_account


def register(registry) -> None:
    register_account(registry)


__all__ = ["register"]
