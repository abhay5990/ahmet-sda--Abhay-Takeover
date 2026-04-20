from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from apps.inventory.services import resolve_game, resolve_owned_product_status
from apps.sync.enums import ResourceType, SyncMode
from apps.sync.models import RawPayload, SyncCheckpoint
from apps.sync.services.base import BaseSyncService
from core.enums import ProductCategory
from . import mapper

if TYPE_CHECKING:
    from apps.integrations.models import IntegrationAccount

logger = logging.getLogger(__name__)


# Statuses to fetch, in order (Eldorado API uses PascalCase: Active, Paused)
_FETCH_STATUSES = ('Active', 'Paused')

# Eldorado search default page size
_PAGE_SIZE = 40

# Eldorado offer lifetime is fixed at 21 days
_OFFER_LIFETIME_DAYS = 21


def _expire_to_listed(expire_dt):
    """Derive listed_at from expireDate by subtracting the fixed offer lifetime."""
    if expire_dt is None:
        return None
    return expire_dt - timedelta(days=_OFFER_LIFETIME_DAYS)


class EldoradoOfferSyncService(BaseSyncService):
    """Offer sync orchestration for Eldorado.

    Fetches ``listed`` and ``paused`` offers sequentially within a
    single sync run using ``checkpoint.meta._current_status`` to
    track which status is being fetched.

    Credentials enrichment is handled in ``prepare_item`` via the
    credentials API endpoint (per-offer call).

    Parse phase upserts into the ``Listing`` table and creates
    ``ListingOwnedProduct`` M2M links for instant offers whose
    credentials match an existing ``OwnedProduct``.

    Eldorado API returns offers sorted by ``expireDate`` descending
    (page 1 = newest expire dates). For incremental mode, the service
    stops when it encounters an offer whose ``expireDate`` is older
    than the checkpoint's ``last_seen_remote_timestamp``.
    """

    resource_type = ResourceType.LISTINGS

    def __init__(self, provider=None, client=None) -> None:
        self.provider = provider
        self.client = client
        self._stop_timestamp = None

    # ── Hook implementations ──────────────────────────────────────────

    def fetch_page(
        self,
        account: IntegrationAccount,
        checkpoint: SyncCheckpoint,
    ) -> tuple[list[dict], str]:
        """Fetch one page of offers, cycling through statuses sequentially.

        Status progression: listed (all pages) → paused (all pages) → done.
        Tracked via ``checkpoint.meta._current_status``.
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
            page_num = checkpoint.meta.get('_incremental_page', 1)
        else:
            page_num = int(checkpoint.cursor) if checkpoint.cursor else 1

        result = self.provider.fetch_products(
            self.client,
            params={
                'offerState': status,
                'pageIndex': page_num,
                'pageSize': _PAGE_SIZE,
            },
        )

        if not result.ok or result.data is None:
            error_msg = ''
            if result.error:
                error_msg = result.error.message
            raise RuntimeError(
                f"Eldorado API error on page {page_num} "
                f"(status={status}): {error_msg}"
            )

        page = result.data
        items: list[dict] = []
        for offer in page.results:
            if hasattr(offer, 'model_dump'):
                items.append(offer.model_dump())
            elif isinstance(offer, dict):
                items.append(offer)
            else:
                items.append(dict(offer))

        if not items:
            return [], ''

        # Determine next page from pagination metadata
        current_page = page.pageIndex
        total_pages = page.totalPages
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

    def is_already_seen(
        self,
        item: dict,
        stop_remote_id: str,
    ) -> bool:
        """Stop incremental sync when we hit an already-seen offer.

        Two stop conditions (API sorted by expireDate descending):
        1. Exact remote_id match
        2. Offer expireDate older than checkpoint timestamp
           (all subsequent offers also have older expireDates → safe to stop)
        """
        if not stop_remote_id:
            return False

        if self.extract_remote_id(item) == stop_remote_id:
            return True

        if self._stop_timestamp:
            item_ts = self.extract_remote_timestamp(item)
            if item_ts and item_ts < self._stop_timestamp:
                logger.info(
                    "Timestamp-based stop: offer %s (expireDate=%s) "
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
        return mapper.parse_iso_timestamp(item.get('expireDate'))

    def prepare_item(
        self,
        item: dict,
        account: IntegrationAccount,
    ) -> tuple[dict, dict]:
        """Enrich offers with credentials from the API.

        Every offer gets credentials fetched via the dedicated endpoint
        since the search response does not include accountsDetails.
        """
        offer_id = str(item.get('id') or '')
        try:
            result = self.provider.fetch_offer_account_details(
                self.client, offer_id,
            )
            if result.ok and result.data:
                entries = []
                details = result.data
                if hasattr(details, 'accountsDetails'):
                    for entry in details.accountsDetails:
                        if hasattr(entry, 'model_dump'):
                            entries.append(entry.model_dump())
                        elif isinstance(entry, dict):
                            entries.append(entry)
                        else:
                            entries.append(dict(entry))

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
        game = resolve_game('eldorado', game_ext_id) if game_ext_id else None

        instant = mapper.is_instant(payload)

        defaults = {
            'is_instant': instant,
            'product_category': mapper.map_category(payload.get('category')),
            'status': mapper.map_status(payload.get('offerState', '')),
            'title': (payload.get('offerTitle') or '')[:500],
            'price': price_value,
            'currency': currency,
            'game': game,
            'sub_platform': mapper.extract_sub_platform(payload),
            'listed_at': _expire_to_listed(
                mapper.parse_iso_timestamp(payload.get('expireDate')),
            ),
            'last_synced_at': raw_payload.fetched_at,
            'raw_data': payload,
        }

        result = self._upsert_listing(raw_payload, defaults)

        # OwnedProduct link-or-create for instant offers
        if instant:
            self._link_or_create_owned_products(
                raw_payload, payload, game, price_value, currency,
            )

        return result

    # ── Private helpers ───────────────────────────────────────────────

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

        # Parse full credentials from entries
        entries = payload.get('_credential_entries') or []
        parsed_list = mapper.parse_credentials_from_credential_entries(entries)

        if not parsed_list:
            return

        try:
            listing = Listing.objects.get(
                integration_account=raw_payload.integration_account,
                store_listing_id=raw_payload.remote_id,
            )
        except Listing.DoesNotExist:
            return

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
