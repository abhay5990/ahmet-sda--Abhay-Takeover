from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apps.inventory.services import resolve_game, resolve_owned_product_status
from apps.posting.models import GameVariantMapping
from apps.sync.enums import ResourceType, SyncMode
from apps.sync.models import RawPayload, SyncCheckpoint
from apps.sync.services.base import BaseSyncService
from core.marketplace.enrichment import collect_credential_entries
from core.marketplace.normalizers import normalize_offer_response
from core.enums import ProductCategory
from . import mapper

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationAccount

logger = logging.getLogger(__name__)


# Statuses to fetch, in order
_FETCH_STATUSES = ('listed', 'draft')


class GameboostOfferSyncService(BaseSyncService):
    """Offer sync orchestration for Gameboost.

    Fetches ``listed`` and ``draft`` offers sequentially within a
    single sync run using ``checkpoint.meta._current_status`` to
    track which status is being fetched.

    Credentials enrichment for new offers (credentials.login is None)
    is handled in ``prepare_item`` via the credentials API endpoint.

    Parse phase upserts into the ``Listing`` table and creates
    ``ListingOwnedProduct`` M2M links for instant offers whose
    credentials match an existing ``OwnedProduct``.
    """

    resource_type = ResourceType.LISTINGS

    DEFAULT_PAGE_SIZE = 50
    BACKFILL_SORT = 'created_at'
    INCREMENTAL_SORT = '-updated_at'

    def __init__(self, provider=None, client=None) -> None:
        self.provider = provider
        self.client = client
        self._stop_timestamp = None
        self._variant_slug_lookups: dict[int, mapper.VariantSlugLookup] = {}

    # ── Hook implementations ──────────────────────────────────────────

    def fetch_page(
        self,
        account: IntegrationAccount,
        checkpoint: SyncCheckpoint,
    ) -> tuple[list[dict], str]:
        """Fetch one page of offers, cycling through statuses sequentially.

        Status progression: listed (all pages) → draft (all pages) → done.
        Tracked via ``checkpoint.meta._current_status``.

        Important: ``BaseSyncService._fetch_loop`` breaks on empty items,
        so when a status is exhausted we immediately fetch the first page
        of the next status in the same call rather than returning empty.
        """
        # Snapshot stop timestamp once for incremental mode
        if (
            checkpoint.mode == SyncMode.INCREMENTAL
            and self._stop_timestamp is None
            and checkpoint.last_seen_remote_timestamp
        ):
            self._stop_timestamp = checkpoint.last_seen_remote_timestamp

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
        """Fetch a single page for a given status filter."""
        if checkpoint.mode == SyncMode.INCREMENTAL:
            page = checkpoint.meta.get('_incremental_page', 1)
            sort = self.INCREMENTAL_SORT
        else:
            page = int(checkpoint.cursor) if checkpoint.cursor else 1
            sort = self.BACKFILL_SORT

        result = self.provider.fetch_products(
            self.client,
            params={
                'filter[status]': status,
                'page': page,
                'per_page': self.DEFAULT_PAGE_SIZE,
                'sort': sort,
            },
        )

        if not result.ok:
            error_msg = ''
            if result.error:
                error_msg = result.error.message
            raise RuntimeError(
                f"Gameboost API error on page {page} "
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
        last_page = pagination.get('last_page', current_page)

        has_next_page = current_page < last_page

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

    def is_already_seen(
        self,
        item: dict,
        stop_remote_id: str,
    ) -> bool:
        """Stop incremental sync when we hit an already-seen offer.

        Two stop conditions (sorted by -updated_at):
        1. Exact remote_id match
        2. Offer updated_at older than checkpoint timestamp
           (all subsequent offers are also older → safe to stop)
        """
        if not stop_remote_id:
            return False

        if str(item.get('id') or '').strip() == stop_remote_id:
            return True

        # Timestamp-based stop: with -updated_at sort, once we hit
        # an offer older than last sync, everything after is also older.
        if self._stop_timestamp:
            item_ts = self.extract_remote_timestamp(item)
            if item_ts and item_ts < self._stop_timestamp:
                logger.info(
                    "Timestamp-based stop: offer %s (updated_at=%s) "
                    "is older than checkpoint (%s)",
                    self.extract_remote_id(item),
                    item_ts.isoformat(),
                    self._stop_timestamp.isoformat(),
                )
                return True

        return False

    def extract_remote_id(self, item: dict) -> str:
        return str(item.get('id') or '').strip()

    def extract_remote_timestamp(self, item: dict):
        return mapper.parse_unix_timestamp(
            item.get('updated_at') or item.get('created_at'),
        )

    def prepare_item(
        self,
        item: dict,
        account: IntegrationAccount,
    ) -> tuple[dict, dict]:
        """Enrich new offers with credentials from the API.

        Legacy offers (credentials.login is not None) pass through
        unchanged — their credentials are already in the offer body.
        """
        if mapper.is_legacy_offer(item):
            return item, {'credentials_source': 'inline'}

        offer_id = str(item.get('id') or '')
        try:
            result = self.client.list_offer_credentials(
                account_id=offer_id,
            )
            if result.ok and result.data:
                entries = collect_credential_entries(result.data)
                item = {**item, '_credential_entries': entries}
                return item, {'credentials_source': 'api'}

            logger.warning(
                "No credentials returned for offer %s", offer_id,
            )
            return item, {'credentials_source': 'api_empty'}

        except Exception as exc:
            logger.warning(
                "Credentials fetch failed for offer %s: %s",
                offer_id, exc,
            )
            return item, {
                'credentials_source': 'api_failed',
                'credentials_error': str(exc),
            }

    def parse_and_apply(self, raw_payload: RawPayload) -> str | None:
        """Parse raw offer payload, upsert Listing, and link OwnedProducts."""
        payload = raw_payload.payload
        price_value, currency = mapper.extract_price(payload)

        game_ext_id = mapper.extract_game_external_id(payload)
        game = resolve_game('gameboost', game_ext_id) if game_ext_id else None
        slug_lookup = self._get_variant_slug_lookup(game) if game else None

        is_instant = not payload.get('is_manual_delivery', False)

        defaults = {
            'is_instant': is_instant,
            'product_category': ProductCategory.ACCOUNTS,
            'status': mapper.map_status(payload.get('status', '')),
            'title': (payload.get('title') or '')[:500],
            'price': price_value,
            'currency': currency,
            'game': game,
            'variant': mapper.extract_variant(
                payload,
                slug_lookup=slug_lookup,
                game_slug=game.slug if game else '',
            ),
            'listed_at': mapper.parse_unix_timestamp(
                payload.get('listed_at'),
            ),
            'last_synced_at': raw_payload.fetched_at,
            'raw_data': normalize_offer_response('gameboost', payload),
        }

        result = self._upsert_listing(raw_payload, defaults)

        # OwnedProduct link-or-create for instant offers
        if is_instant:
            self._link_or_create_owned_products(
                raw_payload, payload, game, price_value, currency,
            )

        return result

    # ── Private helpers ───────────────────────────────────────────────

    def _get_variant_slug_lookup(self, game) -> mapper.VariantSlugLookup:
        """Build a typed GameBoost external value -> slug lookup for one game."""
        cached = self._variant_slug_lookups.get(game.id)
        if cached is not None:
            return cached

        lookup: mapper.VariantSlugLookup = {}
        mappings = (
            GameVariantMapping.objects
            .select_related('variant')
            .filter(variant__game=game, marketplace='gameboost')
            .order_by('variant__type', 'variant__sort_order')
        )
        for mapping in mappings:
            type_lookup = lookup.setdefault(mapping.variant.type, {})
            type_lookup.setdefault(mapping.external_id, mapping.variant.slug)
            if mapping.external_name:
                type_lookup.setdefault(mapping.external_name, mapping.variant.slug)

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

    def _link_or_create_owned_products(
        self,
        raw_payload: RawPayload,
        payload: dict,
        game,
        price,
        currency: str,
    ) -> None:
        """Link Listing to OwnedProducts, creating them if needed.

        For each credential entry, get-or-create OwnedProduct with
        status=LISTED, then create M2M link.
        """
        from apps.inventory.enums import OwnedProductStatus
        from apps.listings.models import Listing, ListingOwnedProduct
        from apps.sync.services.shared.owned_product import get_or_create_owned_product

        category = game.category if game else None
        if not category:
            return

        # Parse full credentials — 3-step fallback:
        # 1. credentials dict (legacy inline structured)
        # 2. _credential_entries (API entries, free text → shared parser)
        # 3. delivery_instructions (free text → shared parser)
        parsed_list = []

        if mapper.is_legacy_offer(payload):
            parsed = mapper.parse_credentials_from_legacy(payload)
            if parsed.login:
                parsed_list.append(parsed)

        if not parsed_list:
            entries = payload.get('_credential_entries') or []
            parsed_list = mapper.parse_credentials_from_entries(entries)

        if not parsed_list:
            parsed = mapper.parse_credentials_from_delivery_instructions(payload)
            if parsed.login:
                parsed_list.append(parsed)

        if not parsed_list:
            return

        try:
            listing = Listing.objects.get(
                integration_account=raw_payload.integration_account,
                store_listing_id=raw_payload.remote_id,
            )
        except Listing.DoesNotExist:
            return

        # Price / 2 as cost estimate
        cost = price / 2 if price else None

        for parsed in parsed_list:
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
                resolve_owned_product_status(owned)
