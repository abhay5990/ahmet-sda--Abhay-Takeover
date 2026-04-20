"""Dropship resolver — duplicate check for source items."""

from __future__ import annotations

from typing import Any

from apps.inventory.enums import DropshipProductStatus
from apps.inventory.models import DropshipProduct
from apps.posting.services.dropship.source_provider import DropshipSourceProvider


class DuplicateItem(Exception):
    """Raised when source_item_id already exists as LISTED DropshipProduct."""

    def __init__(self, source_item_id: int | str, reason: str = ''):
        self.source_item_id = source_item_id
        self.reason = reason or f"Item {source_item_id} already listed"
        super().__init__(self.reason)


class DropshipResolver:
    """Checks for duplicates using the source provider's extract_item_id.

    Loads all LISTED source_product_ids into memory at init time for O(1) lookups.
    Fresh instance should be created each cycle to pick up DB changes.
    """

    def __init__(self) -> None:
        # LISTED: already posted, do not re-post
        # SOLD: buyer purchased, do not re-post
        # DELETED: removed due to price change → poster handles UPDATE, resolver does not block
        self._listed_ids: set[str] = set(
            str(x) for x in DropshipProduct.objects
            .filter(status__in=[
                DropshipProductStatus.LISTED,
                DropshipProductStatus.SOLD,
            ])
            .values_list('source_product_id', flat=True)
        )

    def resolve(
        self,
        item: dict[str, Any],
        source_provider: DropshipSourceProvider,
    ) -> None:
        """Validate item is not a duplicate.

        Args:
            item: Raw item dict from source platform API.
            source_provider: Provider to extract item ID.

        Raises:
            DuplicateItem: If source_item_id is already LISTED or missing.
        """
        try:
            source_item_id = source_provider.extract_item_id(item)
        except (ValueError, KeyError) as e:
            raise DuplicateItem(0, str(e))

        str_id = str(source_item_id)
        if str_id in self._listed_ids:
            raise DuplicateItem(source_item_id)

        # Track newly resolved items within this cycle to avoid duplicates
        # from the same fetch batch
        self._listed_ids.add(str_id)
