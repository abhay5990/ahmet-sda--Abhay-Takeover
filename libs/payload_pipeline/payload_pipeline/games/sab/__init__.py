"""Steal-A-Brainrot slices for payload_pipeline."""
from .item import register as register_item


def register(registry) -> None:
    register_item(registry)


__all__ = ["register"]
