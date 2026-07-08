from __future__ import annotations
import logging
from .models import SabResolvedItem
from .sources import SabEldoradoSourceAdapter

logger = logging.getLogger(__name__)

class SabItemResolver:
    def __init__(self):
        self._adapter = SabEldoradoSourceAdapter()

    def resolve(self, request):
        raw = None
        if hasattr(request, 'source'):
            raw = request.source("eldorado")
        elif hasattr(request, 'sources'):
            raw = (request.sources or {}).get("eldorado")
        if raw is None:
            raise ValueError("SAB item requires 'eldorado' source")
        parsed = self._adapter.parse(raw)
        if parsed is None:
            raise ValueError("Could not parse Eldorado offer")
        return SabResolvedItem(
            offer_id=parsed["offer_id"],
            item_name=parsed["item_name"],
            rarity=parsed["rarity"],
            ms_min=parsed["ms_min"],
            ms_max=parsed["ms_max"],
            mutations=parsed["mutations"],
            price=parsed["price"],
            quantity=parsed["quantity"],
        )
