"""
Google Sheets client factory.

Creates configured GoogleSheetsClient instances from service account info.
"""

from __future__ import annotations

from typing import Any

from apis_sdk.clients.services.google_sheets.client import GoogleSheetsClient


class GoogleSheetsFactory:
    """Factory for creating Google Sheets client instances."""

    @staticmethod
    def create(*, service_account_info: dict[str, Any]) -> GoogleSheetsClient:
        """Create a GoogleSheetsClient from service account credentials.

        Args:
            service_account_info: Parsed JSON dict from a Google service account key file.

        Returns:
            Ready-to-use GoogleSheetsClient.
        """
        return GoogleSheetsClient(service_account_info=service_account_info)
