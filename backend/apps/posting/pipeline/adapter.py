"""Payload pipeline adapter — lazy singleton + Django-aware prepare/build API."""

from __future__ import annotations

import logging

from payload_pipeline import PayloadPipeline, build_default_registry
from payload_pipeline.core.contracts import (
    ListingKind,
    PipelineResult,
    PrepareResult,
    PreparedListing,
)
from payload_pipeline.shared.media import NullMediaPublisher

from .context import build_context
from .request import build_request

logger = logging.getLogger(__name__)

_pipeline: PayloadPipeline | None = None


def _build_media_publisher():
    """Build HostedMediaPublisher from active ServiceCredential records.

    Returns NullMediaPublisher if either credential is missing or inactive.
    """
    try:
        from apps.integrations.models import ServiceCredential
        from apps.integrations.services.registry import get_service
        from .media import DropboxImageUploader, ImageShackAlbumUploader
        from payload_pipeline.shared.media import HostedMediaPublisher

        dropbox_cred = ServiceCredential.objects.filter(
            service_type='dropbox', is_active=True,
        ).first()
        if not dropbox_cred:
            logger.info("No active Dropbox credential — media upload disabled")
            return NullMediaPublisher()

        imageshack_cred = ServiceCredential.objects.filter(
            service_type='imageshack', is_active=True,
        ).first()
        if not imageshack_cred:
            logger.info("No active ImageShack credential — media upload disabled")
            return NullMediaPublisher()

        dropbox_svc = get_service('dropbox')
        imageshack_svc = get_service('imageshack')

        if not dropbox_svc or not imageshack_svc:
            logger.warning("Service definitions not found — media upload disabled")
            return NullMediaPublisher()

        dropbox_facade = dropbox_svc.build_client(dropbox_cred)
        imageshack_facade = imageshack_svc.build_client(imageshack_cred)

        imageshack_creds = imageshack_cred.credentials or {}

        return HostedMediaPublisher(
            dropbox_uploader=DropboxImageUploader(dropbox_facade, dropbox_cred),
            imageshack_processor=ImageShackAlbumUploader(
                imageshack_facade,
                album_prefix=imageshack_creds.get('album_prefix', 'AC'),
            ),
        )

    except Exception as exc:
        logger.warning("Failed to build media publisher: %s", exc)
        return NullMediaPublisher()


def _get_pipeline() -> PayloadPipeline:
    """Return the shared pipeline singleton, initialising it on first call."""
    global _pipeline
    if _pipeline is None:
        publisher = _build_media_publisher()
        _pipeline = PayloadPipeline(build_default_registry(), media_publisher=publisher)
        logger.debug(
            "PayloadPipeline initialised (media_publisher=%s)",
            type(publisher).__name__,
        )
    return _pipeline


def reset_pipeline() -> None:
    """Force re-initialisation on next call (e.g. after credential update)."""
    global _pipeline
    _pipeline = None


def _build_imgur_downloader(proxy_pool=None):
    """Build ImgurAlbumDownloader from active ServiceCredential.

    Returns None if the credential is missing or inactive.
    """
    try:
        from apps.integrations.models import ServiceCredential, ServiceType
        from apps.integrations.services.registry import get_service
        from .media import ImgurAlbumDownloader

        cred = ServiceCredential.objects.filter(
            service_type=ServiceType.IMGUR,
            is_active=True,
        ).first()
        if not cred:
            logger.info("No active Imgur credential — album download disabled")
            return None

        imgur_svc = get_service('imgur')
        if not imgur_svc:
            logger.warning("Imgur service definition not found — album download disabled")
            return None

        facade = imgur_svc.build_client(cred)
        proxy_record = proxy_pool.acquire() if proxy_pool else None
        cdn_proxy_url = proxy_record.to_url() if proxy_record else None
        return ImgurAlbumDownloader(facade, cdn_proxy_url=cdn_proxy_url)

    except Exception as exc:
        logger.warning("Failed to build ImgurAlbumDownloader: %s", exc)
        return None


def prepare(
    *,
    game_slug: str,
    sources: dict,
    kind: ListingKind,
    disable_media: bool = True,
    lzt_image_fetcher=None,
    imgur_album_downloader=None,
) -> PrepareResult:
    """Run the shared preparation phase (resolve → validate → compose).

    Called once per login in the producer thread.  Result is pushed to store
    queues; each store consumer thread calls ``build()`` separately.

    Args:
        game_slug:              Canonical game slug from game_mapp.json.
        sources:                Raw source dict, e.g. {'lzt': raw_data_dict}.
        kind:                   STOCK or DROPSHIPPING.
        disable_media:          Skip image download/upload (default True).
        lzt_image_fetcher:      Optional LZT image fetcher for media steps.
        imgur_album_downloader: Optional ImgurAlbumDownloader (AlbumDownloader protocol).

    Returns:
        PrepareResult — always check ``.success`` before using ``.prepared``.
    """
    request = build_request(
        game_slug=game_slug,
        sources=sources,
        kind=kind,
        disable_media=disable_media,
        lzt_image_fetcher=lzt_image_fetcher,
        imgur_album_downloader=imgur_album_downloader,
    )
    return _get_pipeline().prepare_once(request)


def build(
    *,
    prepared: PreparedListing,
    marketplace: str,
    pricing_defaults,
    store,
    kind: ListingKind,
    sub_platform: str = '',
) -> PipelineResult:
    """Run the marketplace-specific build phase.

    Called once per store in consumer threads.

    Args:
        prepared:         Output of ``prepare()`` — resolved subject + listing draft.
        marketplace:      Provider slug ('eldorado', 'g2g', 'gameboost', 'playerauctions').
        pricing_defaults: PricingDefaults dataclass (stock) or DropshipTargetURL
                          (dropship). Duck-typed: must expose multiplier_low/mid/high,
                          min_price, forced_ending fields.
        store:            IntegrationAccount — used for G2G seller_id lookup.
        kind:             STOCK or DROPSHIPPING.
        sub_platform:     Pre-selected sub-platform (empty string = not applicable).

    Returns:
        PipelineResult — always check ``.success`` before using ``.payload``.
    """
    ctx = build_context(
        marketplace=marketplace,
        pricing_defaults=pricing_defaults,
        store=store,
        kind=kind,
        sub_platform=sub_platform,
    )
    return _get_pipeline().build(prepared, ctx)


def build_bulk(
    *,
    prepared: PreparedListing,
    marketplace: str,
    pricing_defaults,
    store,
    kind: ListingKind,
    sub_platform: str = '',
) -> PipelineResult:
    """Run the marketplace-specific bulk build phase (Excel row dict).

    Same as :func:`build` but produces a bulk/Excel payload via
    ``build_bulk_payload()`` instead of ``build_payload()``.
    """
    ctx = build_context(
        marketplace=marketplace,
        pricing_defaults=pricing_defaults,
        store=store,
        kind=kind,
        sub_platform=sub_platform,
    )
    return _get_pipeline().build_bulk(prepared, ctx)
