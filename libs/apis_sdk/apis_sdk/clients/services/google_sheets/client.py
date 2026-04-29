"""
Google Sheets API client.

Wrapper around gspread for reading/writing spreadsheet data
using a Google service account.

Usage:
    from apis_sdk.clients.services.google_sheets.client import GoogleSheetsClient

    client = GoogleSheetsClient(service_account_info={...})
    rows = client.read_sheet("spreadsheet_id", "Sheet1")
    client.write_sheet("spreadsheet_id", "Sheet1", [["A1", "B1"], ["A2", "B2"]])
"""

from __future__ import annotations

import logging
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


class GoogleSheetsClient:
    """Low-level Google Sheets client backed by gspread + service account."""

    PROVIDER = "google_sheets"

    def __init__(self, service_account_info: dict[str, Any]) -> None:
        creds = Credentials.from_service_account_info(service_account_info, scopes=_SCOPES)
        self._gc = gspread.authorize(creds)
        self._email: str = service_account_info.get("client_email", "")

    @property
    def service_account_email(self) -> str:
        return self._email

    # -- read -----------------------------------------------------------------

    def read_sheet(
        self,
        spreadsheet_id: str,
        sheet_name: str,
    ) -> list[list[str]]:
        """Read all rows from a worksheet.

        Returns a list of rows (each row is a list of cell values as strings).
        """
        spreadsheet = self._gc.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)
        return worksheet.get_all_values()

    def read_sheet_as_dicts(
        self,
        spreadsheet_id: str,
        sheet_name: str,
    ) -> list[dict[str, str]]:
        """Read all rows as dicts keyed by the header row."""
        spreadsheet = self._gc.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)
        return worksheet.get_all_records()

    # -- write ----------------------------------------------------------------

    def write_sheet(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        rows: list[list[Any]],
        *,
        clear_first: bool = True,
    ) -> int:
        """Write rows to a worksheet.

        Args:
            spreadsheet_id: Google Sheets document ID.
            sheet_name: Target worksheet name.
            rows: 2D list of values (first row is typically headers).
            clear_first: If True, clears existing content before writing.

        Returns:
            Number of rows written.
        """
        spreadsheet = self._gc.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)
        if clear_first:
            worksheet.clear()
        if rows:
            worksheet.update(rows, value_input_option="USER_ENTERED")
        return len(rows)

    def append_rows(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        rows: list[list[Any]],
    ) -> int:
        """Append rows to the end of a worksheet.

        Returns:
            Number of rows appended.
        """
        spreadsheet = self._gc.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)
        if rows:
            worksheet.append_rows(rows, value_input_option="USER_ENTERED")
        return len(rows)

    def get_or_create_worksheet(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        rows: int = 1000,
        cols: int = 26,
    ) -> "gspread.Worksheet":
        """Return an existing worksheet or create a new one."""
        spreadsheet = self._gc.open_by_key(spreadsheet_id)
        try:
            return spreadsheet.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            return spreadsheet.add_worksheet(title=sheet_name, rows=rows, cols=cols)

    def write_to_sheet(
        self,
        spreadsheet_id: str,
        sheet_name: str,
        rows: list[list[Any]],
    ) -> int:
        """Write rows to a worksheet, creating it if it doesn't exist.

        Clears existing content before writing.
        Returns number of rows written.
        """
        ws = self.get_or_create_worksheet(spreadsheet_id, sheet_name)
        ws.clear()
        if rows:
            ws.update(rows, value_input_option="USER_ENTERED")
        return len(rows)

    # -- utility --------------------------------------------------------------

    def list_worksheets(self, spreadsheet_id: str) -> list[str]:
        """Return worksheet names in a spreadsheet."""
        spreadsheet = self._gc.open_by_key(spreadsheet_id)
        return [ws.title for ws in spreadsheet.worksheets()]

    def test_connection(self, spreadsheet_id: str) -> tuple[bool, str]:
        """Verify the service account can access a spreadsheet.

        Returns (success, message).
        """
        try:
            spreadsheet = self._gc.open_by_key(spreadsheet_id)
            title = spreadsheet.title
            return True, f"Connected: '{title}'"
        except gspread.exceptions.APIError as exc:
            return False, f"API error: {exc}"
        except gspread.exceptions.SpreadsheetNotFound:
            return False, "Spreadsheet not found. Did you share it with the service account?"
        except Exception as exc:
            return False, f"Connection failed: {exc}"
