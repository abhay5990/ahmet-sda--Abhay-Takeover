"""Gerçek Imgur album'den resim indirme integration testi.

Kullanım:
    cd <project-root>
    venv/bin/python tests/integration/test_imgur_album_download.py \
        --album https://imgur.com/a/HASH_BURAYA \
        --client-id CLIENT_ID_BURAYA \
        --output /tmp/imgur_real_test
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

# ── path setup ────────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "libs" / "apis_sdk"))
sys.path.insert(0, str(_ROOT / "backend"))
# ─────────────────────────────────────────────────────────────────────────────


def _build_facade(client_id: str):
    from apis_sdk.clients.media.imgur.config import ImgurConfig
    from apis_sdk.clients.media.imgur.client import ImgurClient
    from apis_sdk.clients.media.imgur.facade import ImgurFacade
    from apis_sdk.infrastructure.http.requests_transport import RequestsTransport

    transport = RequestsTransport()
    client = ImgurClient(config=ImgurConfig(), transport=transport)
    return ImgurFacade(client=client, client_id=client_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Imgur album gerçek indirme testi")
    parser.add_argument("--album", required=True, help="Imgur album URL (imgur.com/a/HASH)")
    parser.add_argument("--client-id", required=True, help="Imgur Client-ID")
    parser.add_argument("--output", default="/tmp/imgur_real_test", help="Çıktı dizini")
    parser.add_argument("--proxy-url", default=None, help="CDN proxy URL (http://user:pass@host:port)")
    args = parser.parse_args()

    from apps.posting.pipeline.media.imgur_downloader_adapter import ImgurAlbumDownloader

    facade = _build_facade(args.client_id)
    downloader = ImgurAlbumDownloader(facade, cdn_proxy_url=args.proxy_url)

    print(f"\nAlbum  : {args.album}")
    print(f"Output : {args.output}")
    print("-" * 50)

    paths = downloader.download_album(args.album, args.output)

    print("-" * 50)
    if paths:
        print(f"✓ {len(paths)} resim indirildi:")
        for p in paths:
            size = os.path.getsize(p)
            print(f"  {os.path.basename(p):30s}  {size:>8,} bytes")
    else:
        print("✗ Hiç resim indirilemedi.")


if __name__ == "__main__":
    main()
