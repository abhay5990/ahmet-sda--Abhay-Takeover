"""Read-only, fail-closed identity lookup for the single SDA PA Mart store."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db.models import Q

if TYPE_CHECKING:
    from apps.listings.models import Listing


_MART_SLUG = 'playerauctions-csgosmurfkings'
_MAX_OFFER_ID_DIGITS = 16


def is_pa_mart_identity_account(integration_account: Any) -> bool:
    """Do not opt other PA stores (or another provider) into renewal aliases."""
    return (
        getattr(integration_account, 'provider', None) == 'playerauctions'
        and getattr(integration_account, 'slug', None) == _MART_SLUG
        and getattr(integration_account, 'pk', None) is not None
    )


def _exact_offer_id(offer_id: Any) -> str | None:
    """Accept only positive, canonical ASCII IDs bounded like Mart renewals."""
    if isinstance(offer_id, bool) or not isinstance(offer_id, (str, int)):
        return None
    # Bound integers before converting, including arbitrarily large inputs.
    if isinstance(offer_id, int):
        if not 0 < offer_id < 10 ** _MAX_OFFER_ID_DIGITS:
            return None
        offer_id = str(offer_id)
    if (
        not 1 <= len(offer_id) <= _MAX_OFFER_ID_DIGITS
        or not offer_id.isascii()
        or not offer_id.isdigit()
        or offer_id.startswith('0')
    ):
        return None
    return offer_id


def resolve_pa_mart_listing(integration_account: Any, offer_id: Any) -> Listing | None:
    """Resolve exactly one current-or-historical Listing in this Mart account.

    Succeeded attempts bind *both* recorded IDs to their original Listing FK,
    so earlier histories survive any number of renewal cycles. Pending,
    rejected and unknown outcomes are not identity evidence. In particular an
    unknown attempt is not promoted here, even if it contains partial verification.
    Current IDs have no priority over historical IDs: a collision returns None.
    No titles, stock credentials, remote reads or writes participate in lookup.
    """
    if not is_pa_mart_identity_account(integration_account):
        return None
    exact_id = _exact_offer_id(offer_id)
    if exact_id is None:
        return None

    from apps.listings.models import Listing
    from apps.sync.models import PaMartRenewalAttempt

    historical_listing_ids = PaMartRenewalAttempt.objects.filter(
        integration_account=integration_account,
        listing__integration_account=integration_account,
        status='succeeded',
    ).filter(
        Q(old_offer_id=exact_id) | Q(new_offer_id=exact_id),
    ).values_list('listing_id', flat=True)

    # UNION identities before checking cardinality, never prefer a current ID
    # or the newest ledger row when they identify different Listing records.
    candidates = list(
        Listing.objects.filter(integration_account=integration_account)
        .filter(Q(store_listing_id=exact_id) | Q(pk__in=historical_listing_ids))
        .select_related('dropship_product')
        .order_by('pk')[:2]
    )
    return candidates[0] if len(candidates) == 1 else None
