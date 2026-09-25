from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from apps.inventory.services import resolve_game
from apps.posting.models import GameVariantMapping
from apps.sync.enums import ResourceType, SyncMode
from apps.sync.models import RawPayload, SyncCheckpoint
from apps.sync.services.base import BaseSyncService
from core.marketplace.normalizers import normalize_offer_response
from . import mapper

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationAccount

logger = logging.getLogger(__name__)


# Statuses to fetch, in order
_FETCH_STATUSES = ('Active', 'Hidden')

# Default offer duration (days) when details.offerDuration is missing
_DEFAULT_OFFER_DURATION_DAYS = 30


def _expire_to_listed(expire_dt, payload):
    """Derive listed_at from expired_time by subtracting offerDuration."""
    if expire_dt is None:
        return None
    details = payload.get('details') or {}
    duration = details.get('offerDuration') or _DEFAULT_OFFER_DURATION_DAYS
    return expire_dt - timedelta(days=int(duration))


def _payload_expiry(payload):
    """Return the authoritative PlayerAuctions expiry timestamp when present."""
    return mapper.parse_pa_datetime(
        payload.get('expired_time_string')
        or payload.get('expiredTimeString')
        or '',
    )


class PlayerAuctionsOfferSyncService(BaseSyncService):
    """Offer sync orchestration for PlayerAuctions.

    Fetches ``Active`` and ``Hidden`` offers sequentially within a
    single sync run using ``checkpoint.meta._current_status`` to
    track which status is being fetched.

    The list endpoint returns flat offer summaries (offerId, systemStatus,
    title, totalPrice, etc.) but does NOT include ``details`` (credentials,
    gameId, isAuto).  Credentials and game info are only available from the
    per-offer detail endpoint (``get_offer_details``).

    ``prepare_item`` enriches each offer with detail data so that
    ``parse_and_apply`` has access to credentials and game info.

    Parse phase upserts into the ``Listing`` table and creates
    ``ListingOwnedProduct`` M2M links for instant offers whose
    credentials match an existing ``OwnedProduct``.
    """

    resource_type = ResourceType.LISTINGS

    DEFAULT_PAGE_SIZE = 50

    def __init__(self, provider=None, client=None) -> None:
        self.provider = provider
        self.client = client
        self._variant_slug_lookups: dict[int, mapper.VariantSlugLookup] = {}

    def run(self, account, mode, phase='full'):
        """Reset auth failure flag before each sync run."""
        if self.client and hasattr(self.client, 'reset_auth_failure'):
            self.client.reset_auth_failure()
        return super().run(account, mode, phase)

    # ── Hook implementations ──────────────────────────────────────────

    def fetch_page(
        self,
        account: IntegrationAccount,
        checkpoint: SyncCheckpoint,
    ) -> tuple[list[dict], str]:
        """Fetch one page of offers, cycling through statuses sequentially.

        Status progression: Active (all pages) → Hidden (all pages) → done.
        Tracked via ``checkpoint.meta._current_status``.
        """
        if self._uses_mct_official_offer_snapshot():
            return self._fetch_mct_official_active_snapshot_page(
                account, checkpoint,
            )

        current_status = checkpoint.meta.get(
            '_current_status', _FETCH_STATUSES[0],
        )

        items, next_cursor = self._fetch_status_page(
            account, checkpoint, current_status,
        )

        if items:
            return items, next_cursor

        # Current status returned no items — try next status
        status_idx = _FETCH_STATUSES.index(current_status)
        if status_idx + 1 < len(_FETCH_STATUSES):
            next_status = _FETCH_STATUSES[status_idx + 1]

            checkpoint.meta = {
                **checkpoint.meta,
                '_current_status': next_status,
                '_incremental_page': 1,
            }
            checkpoint.cursor = '1'
            checkpoint.save(
                update_fields=['meta', 'cursor', 'updated_at'],
            )

            logger.info(
                "Status '%s' exhausted, moving to '%s'",
                current_status, next_status,
            )

            return self._fetch_status_page(
                account, checkpoint, next_status,
            )

        # All statuses exhausted
        return [], ''

    def _fetch_status_page(
        self,
        account: IntegrationAccount,
        checkpoint: SyncCheckpoint,
        status: str,
    ) -> tuple[list[dict], str]:
        """Fetch a single page for a given listing status filter."""
        if checkpoint.mode == SyncMode.INCREMENTAL:
            page = checkpoint.meta.get('_incremental_page', 1)
        else:
            page = int(checkpoint.cursor) if checkpoint.cursor else 1

        result = self.provider.fetch_products(
            self.client,
            page=page,
            page_size=self.DEFAULT_PAGE_SIZE,
            listing_status=status,
        )

        if not result.ok:
            error_msg = ''
            if result.error:
                error_msg = result.error.message
            raise RuntimeError(
                f"PlayerAuctions API error on page {page} "
                f"(status={status}): {error_msg}"
            )

        items: list[dict] = []
        for offer in result.data or []:
            if hasattr(offer, 'model_dump'):
                items.append(offer.model_dump())
            elif isinstance(offer, dict):
                items.append(offer)
            else:
                items.append(dict(offer))

        if not items:
            return [], ''

        # Determine next page from pagination metadata
        pagination = result.meta.get('pagination', {})
        current_page = pagination.get('current_page', page)
        total_pages = pagination.get('total_pages', current_page)

        has_next_page = current_page < total_pages

        if has_next_page:
            next_cursor = str(current_page + 1)
            if checkpoint.mode == SyncMode.INCREMENTAL:
                checkpoint.meta = {
                    **checkpoint.meta,
                    '_incremental_page': current_page + 1,
                    '_current_status': status,
                }
                checkpoint.save(update_fields=['meta', 'updated_at'])
            return items, next_cursor

        # Last page of this status
        status_idx = _FETCH_STATUSES.index(status)
        if status_idx + 1 < len(_FETCH_STATUSES):
            next_status = _FETCH_STATUSES[status_idx + 1]
            next_cursor = '1'

            checkpoint.meta = {
                **checkpoint.meta,
                '_current_status': next_status,
                '_incremental_page': 1,
            }
            checkpoint.save(update_fields=['meta', 'updated_at'])

            logger.info(
                "Status '%s' exhausted, moving to '%s'",
                status, next_status,
            )
        else:
            next_cursor = ''

        return items, next_cursor

    def _uses_mct_official_offer_snapshot(self) -> bool:
        """Whether this Mart client is restricted to the MCT cache reader."""
        enabled = getattr(
            self.client, 'uses_mct_official_offer_snapshot', None,
        )
        return enabled() is True if callable(enabled) else False

    def _fetch_mct_official_active_snapshot_page(
        self,
        account: IntegrationAccount,
        checkpoint: SyncCheckpoint,
    ) -> tuple[list[dict], str]:
        """Refresh already-known active Mart offers from the MCT Official cache.

        This path intentionally reads no PlayerAuctions credentials, browser
        session, relay, offer detail, or provider search. It sends only the
        numeric IDs already present in SDA as listed Mart records. Absence from
        one cache response is never interpreted as a deletion or pause.
        """
        from apps.listings.enums import ListingStatus
        from apps.listings.models import Listing

        try:
            page = int(checkpoint.cursor) if checkpoint.cursor else 1
        except (TypeError, ValueError):
            page = 1
        page = max(1, page)
        known_ids: list[int] = []
        for value in Listing.objects.filter(
            integration_account=account,
            status=ListingStatus.LISTED,
        ).values_list('store_listing_id', flat=True):
            try:
                offer_id = int(value)
            except (TypeError, ValueError):
                continue
            if offer_id > 0:
                known_ids.append(offer_id)
        known_ids = sorted(set(known_ids))
        if not known_ids:
            return [], ''
        if len(known_ids) > 2000:
            raise RuntimeError(
                'Mart Official active-offer snapshot has more than 2000 SDA-known '
                'active IDs; the safe bridge requires an explicit bounded batch extension.'
            )

        result = self.provider.fetch_products(
            self.client,
            page=page,
            page_size=self.DEFAULT_PAGE_SIZE,
            listing_status='Active',
            offer_ids=known_ids,
        )
        if not result.ok:
            error_msg = result.error.message if result.error else ''
            raise RuntimeError(
                'Mart Official active-offer snapshot is unavailable: '
                f'{error_msg}'
            )

        items = [
            offer.model_dump() if hasattr(offer, 'model_dump')
            else offer if isinstance(offer, dict) else dict(offer)
            for offer in (result.data or [])
        ]
        pagination = result.meta.get('pagination', {})
        current_page = int(pagination.get('current_page', page))
        total_pages = int(pagination.get('total_pages', current_page))
        next_cursor = str(current_page + 1) if current_page < total_pages else ''
        return items, next_cursor

    def is_already_seen(
        self,
        item: dict,
        stop_remote_id: str,
    ) -> bool:
        """Stop incremental sync when we hit an already-seen offer."""
        if self._uses_mct_official_offer_snapshot():
            # Snapshot pages are exact-ID batches rather than a provider-owned
            # newest-first feed, so an old checkpoint must not suppress a later
            # known Mart offer batch.
            return False
        if not stop_remote_id:
            return False
        return self.extract_remote_id(item) == stop_remote_id

    def extract_remote_id(self, item: dict) -> str:
        return str(
            item.get('offer_id')
            or item.get('offerId')
            or item.get('id')
            or '',
        ).strip()

    def extract_remote_timestamp(self, item: dict):
        return mapper.parse_pa_datetime(
            item.get('expired_time_string')
            or item.get('expiredTimeString')
            or '',
        )

    def prepare_item(
        self,
        item: dict,
        account: IntegrationAccount,
    ) -> tuple[dict, dict]:
        """Enrich offer with detail data (credentials, gameId, price).

        The list endpoint only returns flat summaries. The detail endpoint
        returns ``autoDelivery`` (credentials), ``gameId``, ``isAuto``, etc.
        """
        if self._uses_mct_official_offer_snapshot():
            # The cache is deliberately summary-only. Do not request per-offer
            # detail because that would reintroduce a direct PA/relay call and
            # could expose delivery credentials to the sync path.
            return item, {'detail_source': 'mct_official_active_snapshot'}
        offer_id = self.extract_remote_id(item)
        try:
            result = self.client.get_offer_details(
                offer_id=offer_id,
            )
            if result.ok and result.data:
                detail = result.data
                if isinstance(detail, dict):
                    item = {**item, 'details': detail}
                    return item, {'detail_source': 'api'}

            logger.warning(
                "No detail returned for PA offer %s", offer_id,
            )
            return item, {'detail_source': 'api_empty'}

        except Exception as exc:
            logger.warning(
                "Detail fetch failed for PA offer %s: %s",
                offer_id, exc,
            )
            return item, {
                'detail_source': 'api_failed',
                'detail_error': str(exc),
            }

    def parse_and_apply(self, raw_payload: RawPayload) -> str | None:
        """Parse raw offer payload, upsert Listing, and link OwnedProducts."""
        if self._uses_mct_official_offer_snapshot():
            return self._apply_mct_official_active_snapshot(raw_payload)

        payload = raw_payload.payload
        price_value, currency = mapper.extract_price(payload)

        game_ext_id = mapper.extract_game_external_id(payload)
        game = (
            resolve_game('playerauctions', game_ext_id)
            if game_ext_id else None
        )
        slug_lookup = self._get_variant_slug_lookup(game) if game else None

        instant = mapper.is_instant(payload)
        status_str = (
            payload.get('system_status')
            or payload.get('systemStatus')
            or ''
        )

        expiry_at = _payload_expiry(payload)
        defaults = {
            'is_instant': instant,
            'product_category': mapper.map_category(
                payload.get('productType')
                or payload.get('product_type')
                or '',
            ),
            'status': mapper.map_status(status_str),
            'title': (payload.get('title') or '')[:500],
            'price': price_value,
            'currency': currency,
            'game': game,
            'variant': mapper.extract_variant(
                payload,
                slug_lookup=slug_lookup,
                game_slug=game.slug if game else '',
            ),
            'last_synced_at': raw_payload.fetched_at,
            'raw_data': normalize_offer_response('playerauctions', payload),
        }
        # Do not erase an earlier known lifecycle timestamp when the remote
        # summary temporarily omits its expiry.  The following sync with an
        # authoritative value replaces both fields.
        if expiry_at is not None:
            defaults['listed_at'] = _expire_to_listed(expiry_at, payload)
            defaults['marketplace_expires_at'] = expiry_at

        result = self._upsert_listing(raw_payload, defaults)

        # OwnedProduct get-or-create + link for instant offers
        if instant:
            self._link_owned_products(
                raw_payload, payload, game, price_value, currency,
            )

        return result

    def _apply_mct_official_active_snapshot(
        self,
        raw_payload: RawPayload,
    ) -> str | None:
        """Update safe fields on one pre-existing listed Mart record only.

        The MCT snapshot is not a discovery feed. It never creates listings,
        changes game/platform/category/instant ownership, links stock, or
        changes state based on an absent/malformed summary. This prevents
        CodeTracker-owned listings or incomplete records from leaking into SDA.
        """
        from apps.listings.enums import ListingStatus
        from apps.listings.models import Listing

        listing = Listing.objects.filter(
            integration_account=raw_payload.integration_account,
            store_listing_id=raw_payload.remote_id,
            status=ListingStatus.LISTED,
        ).first()
        if listing is None:
            return None

        payload = raw_payload.payload
        updates: list[str] = []
        title = str(payload.get('title') or '').strip()[:500]
        if title and title != listing.title:
            listing.title = title
            updates.append('title')

        price_value, currency = mapper.extract_price(payload)
        if price_value > 0 and (listing.price != price_value or listing.currency != currency):
            listing.price = price_value
            listing.currency = currency
            updates.extend(['price', 'currency'])

        expiry_at = _payload_expiry(payload)
        if expiry_at is not None:
            listed_at = _expire_to_listed(expiry_at, payload)
            if listing.marketplace_expires_at != expiry_at:
                listing.marketplace_expires_at = expiry_at
                updates.append('marketplace_expires_at')
            if listing.listed_at != listed_at:
                listing.listed_at = listed_at
                updates.append('listed_at')

        raw_data = normalize_offer_response('playerauctions', payload)
        if listing.raw_data != raw_data:
            listing.raw_data = raw_data
            updates.append('raw_data')
        listing.last_synced_at = raw_payload.fetched_at
        updates.append('last_synced_at')
        listing.save(update_fields=[*dict.fromkeys(updates), 'updated_at'])
        return 'updated'

    def _reconcile_stale(self, account, run) -> None:
        """Never delete Mart records from an active-only cache snapshot.

        A missing record may be hidden/expired or the worker cache may be
        incomplete. Any status transition requires a separate verified remote
        lifecycle path, never this safe summary reader.
        """
        if self._uses_mct_official_offer_snapshot():
            logger.info(
                'Skipped stale reconciliation for Mart Official active-offer snapshot account=%s',
                account.slug,
            )
            return
        super()._reconcile_stale(account, run)

    # ── Private helpers ───────────────────────────────────────────────

    def _get_variant_slug_lookup(self, game) -> mapper.VariantSlugLookup:
        """Build a typed PlayerAuctions external_id -> slug lookup for one game."""
        cached = self._variant_slug_lookups.get(game.id)
        if cached is not None:
            return cached

        lookup: mapper.VariantSlugLookup = {}
        mappings = (
            GameVariantMapping.objects
            .select_related('variant')
            .filter(variant__game=game, marketplace='playerauctions')
            .order_by('variant__type', 'variant__sort_order')
        )
        for mapping in mappings:
            lookup.setdefault(mapping.variant.type, {}).setdefault(
                mapping.external_id,
                mapping.variant.slug,
            )

        self._variant_slug_lookups[game.id] = lookup
        return lookup

    def _upsert_listing(
        self,
        raw_payload: RawPayload,
        defaults: dict,
    ) -> str:
        """Upsert a Listing row. Returns 'created' or 'updated'."""
        from apps.listings.models import Listing

        listing, created = Listing.objects.update_or_create(
            integration_account=raw_payload.integration_account,
            store_listing_id=raw_payload.remote_id,
            defaults=defaults,
        )
        return 'created' if created else 'updated'

    def _link_owned_products(
        self,
        raw_payload: RawPayload,
        payload: dict,
        game,
        price,
        currency,
    ) -> None:
        """Get-or-create OwnedProduct from offer credentials, then link to Listing.

        PA has one account per offer — single login from autoDelivery.
        """
        from apps.inventory.enums import OwnedProductStatus
        from apps.listings.models import Listing, ListingOwnedProduct
        from apps.sync.services.shared.owned_product import get_or_create_owned_product

        category = game.category if game else None
        if not category:
            return

        parsed = mapper.to_parsed_credentials(payload)
        if not parsed.login:
            return

        try:
            listing = Listing.objects.get(
                integration_account=raw_payload.integration_account,
                store_listing_id=raw_payload.remote_id,
            )
        except Listing.DoesNotExist:
            return

        cost = price / 2 if price else None

        owned = get_or_create_owned_product(
            parsed=parsed,
            category=category,
            game=game,
            source_account=raw_payload.integration_account,
            status=OwnedProductStatus.LISTED,
            price=cost,
            currency=currency,
            raw_data=payload,
        )
        if owned:
            ListingOwnedProduct.objects.get_or_create(
                listing=listing,
                owned_product=owned,
            )
