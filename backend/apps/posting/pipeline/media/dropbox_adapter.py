"""Dropbox adapter — implements ImageUploader protocol."""

from __future__ import annotations

import logging
import os
from datetime import timedelta

import requests as http_requests

from django.utils import timezone

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://api.dropbox.com/oauth2/token"


class DropboxImageUploader:
    """Implements ImageUploader protocol using DropboxFacade.

    Reads files from disk, uploads to Dropbox, returns direct download URLs.
    Handles OAuth2 token refresh transparently.
    """

    def __init__(self, facade, credential) -> None:
        self._facade = facade
        self._credential = credential  # ServiceCredential instance

    def upload_images(self, image_paths: list[str]) -> list[str]:
        """Upload images to Dropbox and return direct download URLs."""
        self._refresh_token_if_needed()

        creds = self._credential.credentials or {}
        upload_folder = creds.get('upload_folder', '/media')
        urls: list[str] = []

        for path in image_paths:
            if not os.path.isfile(path):
                logger.warning("File not found, skipping: %s", path)
                continue
            try:
                file_name = os.path.basename(path)
                dest = f"{upload_folder}/{file_name}"

                with open(path, 'rb') as f:
                    file_data = f.read()

                result = self._facade.upload_and_share(file_data, dest)

                if result.ok and result.data:
                    url = result.data.get('url', '')
                    if url:
                        direct_url = url.replace('dl=0', 'dl=1')
                        urls.append(direct_url)
                else:
                    error_msg = result.error.message if result.error else 'unknown'
                    logger.warning("Dropbox upload failed for %s: %s", path, error_msg)
            except Exception as exc:
                logger.warning("Dropbox upload error for %s: %s", path, exc)

        return urls

    def _refresh_token_if_needed(self) -> None:
        """Check token_expires_at in credentials JSON and refresh if expired."""
        creds = self._credential.credentials or {}
        expires_at_str = creds.get('token_expires_at', '')

        if expires_at_str:
            from django.utils.dateparse import parse_datetime
            expires_at = parse_datetime(expires_at_str)
            if expires_at and timezone.now() < expires_at:
                return  # Token still valid

        refresh_token = creds.get('refresh_token', '')
        app_key = creds.get('app_key', '')
        app_secret = creds.get('app_secret', '')

        if not all([refresh_token, app_key, app_secret]):
            logger.warning("Cannot refresh Dropbox token: missing credentials")
            return

        try:
            resp = http_requests.post(_TOKEN_URL, data={
                'grant_type': 'refresh_token',
                'refresh_token': refresh_token,
                'client_id': app_key,
                'client_secret': app_secret,
            }, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            new_token = data['access_token']
            expires_in = data.get('expires_in', 14400)
            new_expires_at = timezone.now() + timedelta(seconds=expires_in)

            # Update facade in-memory
            self._facade.set_access_token(new_token)

            # Persist to DB
            updated_creds = self._credential.credentials.copy()
            updated_creds['access_token'] = new_token
            updated_creds['token_expires_at'] = new_expires_at.isoformat()
            self._credential.credentials = updated_creds
            self._credential.save(update_fields=['credentials', 'updated_at'])

            logger.info("Dropbox token refreshed, expires at %s", new_expires_at)
        except Exception as exc:
            logger.error("Dropbox token refresh failed: %s", exc)
