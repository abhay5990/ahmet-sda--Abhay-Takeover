"""Media upload adapters for the posting pipeline.

Bridges pipeline protocols (ImageUploader, AlbumUploader) to
SDK facades (DropboxFacade, ImageShackFacade).
"""

from .dropbox_adapter import DropboxImageUploader
from .eldorado_adapter import EldoradoMarketplaceUploader
from .imageshack_adapter import ImageShackAlbumUploader
from .imgur_downloader_adapter import ImgurAlbumDownloader

__all__ = [
    "DropboxImageUploader",
    "EldoradoMarketplaceUploader",
    "ImageShackAlbumUploader",
    "ImgurAlbumDownloader",
]
