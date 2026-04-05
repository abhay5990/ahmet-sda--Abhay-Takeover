"""
apis-sdk — Reusable integration SDK for external provider APIs.

Architecture layers (dependency flows downward):
    application → clients → infrastructure → core
"""

from apis_sdk.version import __version__

__all__ = ["__version__"]
