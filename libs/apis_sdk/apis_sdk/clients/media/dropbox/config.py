"""
Dropbox client configuration.

Holds connection settings for the Dropbox API v2.
The access token is injected separately via the facade.

Note:
    Dropbox uses two separate hosts:
    - ``api_base_url`` for RPC-style endpoints (sharing, metadata)
    - ``content_base_url`` for content-upload endpoints (file upload)
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DropboxConfig(BaseModel):
    """Configuration for the Dropbox API client."""

    api_base_url: str = Field(
        default="https://api.dropboxapi.com/2",
        description="Dropbox RPC API base URL (sharing, metadata).",
    )
    content_base_url: str = Field(
        default="https://content.dropboxapi.com/2",
        description="Dropbox content upload base URL.",
    )
    upload_folder: str = Field(
        default="/media",
        description="Root folder in Dropbox for uploaded media files.",
    )
    timeout: float = Field(
        default=60.0,
        gt=0,
        description="Request timeout in seconds.",
    )

    model_config = {"frozen": True}
