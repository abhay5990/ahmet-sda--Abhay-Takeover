from __future__ import annotations

import json

from .base import AbstractServiceDefinition, ServiceField
from .registry import register_service


@register_service
class GoogleSheetsService(AbstractServiceDefinition):
    """Google Sheets service — read/write spreadsheet data via service account.

    Credentials:
        service_account_json — Full JSON key file content (uploaded via file picker)

    The service account email is extracted from the JSON and displayed as a
    readonly field so the user knows which email to share the spreadsheet with.
    """

    service_type = 'google-sheets'
    display_name = 'Google Sheets'

    @classmethod
    def get_fields(cls) -> list[ServiceField]:
        return [
            ServiceField(
                name='service_account_json',
                label='Service Account JSON',
                field_type='file_json',
                required=True,
                help_text=(
                    'Upload or paste the Google service account key JSON file. '
                    'Required APIs: enable both "Google Sheets API" and "Google Drive API" '
                    'in Google Cloud Console for the service account project.'
                ),
            ),
            ServiceField(
                name='service_account_email',
                label='Service Account Email',
                field_type='readonly',
                required=False,
                help_text='Auto-extracted from the JSON. Share your spreadsheet with this email.',
            ),
        ]

    @classmethod
    def on_credentials_save(cls, credentials: dict) -> dict:
        """Extract service_account_email from the JSON before persisting.

        Called by the form/view layer after the user uploads the JSON file.
        """
        sa_json = credentials.get('service_account_json')
        if isinstance(sa_json, str):
            try:
                sa_json = json.loads(sa_json)
                credentials['service_account_json'] = sa_json
            except (json.JSONDecodeError, TypeError):
                pass
        if isinstance(sa_json, dict):
            credentials['service_account_email'] = sa_json.get('client_email', '')
        return credentials

    @classmethod
    def validate_credentials(cls, credentials: dict) -> list[str]:
        errors = []
        sa_json = credentials.get('service_account_json')
        if not sa_json:
            errors.append('Service Account JSON is required.')
            return errors

        # Parse if still a string
        if isinstance(sa_json, str):
            try:
                sa_json = json.loads(sa_json)
            except (json.JSONDecodeError, TypeError):
                errors.append('Service Account JSON is not valid JSON.')
                return errors

        if not isinstance(sa_json, dict):
            errors.append('Service Account JSON must be a JSON object.')
            return errors

        required_keys = ['type', 'project_id', 'private_key', 'client_email']
        missing = [k for k in required_keys if not sa_json.get(k)]
        if missing:
            errors.append(f'Service Account JSON is missing required keys: {", ".join(missing)}')
        elif sa_json.get('type') != 'service_account':
            errors.append('JSON "type" field must be "service_account".')

        return errors

    @classmethod
    def build_client(cls, credential):
        """Build a GoogleSheetsClient from a ServiceCredential instance."""
        from apis_sdk.factories.google_sheets_factory import GoogleSheetsFactory

        creds = credential.credentials or {}
        sa_json = creds.get('service_account_json', {})
        return GoogleSheetsFactory.create(service_account_info=sa_json)

    @classmethod
    def test_connection(cls, client) -> tuple[bool, str]:
        email = client.service_account_email
        if email:
            return True, f"Authenticated as {email}"
        return False, "Could not determine service account email."
