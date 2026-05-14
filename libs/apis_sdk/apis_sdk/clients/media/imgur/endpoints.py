"""
Imgur API endpoint constants.

Centralized URL paths for the Imgur API v3.
"""


class ImgurEndpoints:
    """Imgur API endpoint paths."""

    UPLOAD_IMAGE = "/image"
    ALBUM = "/album"
    CREDITS = "/credits"

    # public/v1 endpoint — used with ImgurConfig.public_base_url
    ALBUM_FETCH = "/albums/{hash}"
