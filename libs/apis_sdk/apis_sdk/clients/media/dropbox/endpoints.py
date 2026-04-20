"""
Dropbox API endpoint constants.

Centralized URL paths for the Dropbox API v2.

Note:
    Upload endpoints live on ``content.dropboxapi.com``;
    all other endpoints live on ``api.dropboxapi.com``.
"""


class DropboxEndpoints:
    """Dropbox API endpoint paths."""

    # Content endpoints (content_base_url)
    UPLOAD = "/files/upload"

    # RPC endpoints (api_base_url)
    CREATE_SHARED_LINK = "/sharing/create_shared_link_with_settings"
    GET_METADATA = "/files/get_metadata"
    DELETE = "/files/delete_v2"
