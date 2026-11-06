"""Faithful, unchanged Eldorado renewal PUTs built only from a fresh snapshot.

The caller owns the same-offer lease and must dump the private offer with
``exclude_unset=True`` (recursively). Model defaults are not authoritative data.
This module does no I/O and never accepts a listing or cached ``raw_data``.
"""
from __future__ import annotations

from copy import deepcopy
import math
from types import SimpleNamespace
from typing import Any

from apis_sdk.clients.marketplaces.eldorado.delivery_details import (
    EldoradoDeliveryDetailsError,
    preserved_delivery_details,
    to_wire_payload,
)

# Every public field consumed by the full-update builder must be explicit.
_REQUIRED_PUBLIC_FIELDS = frozenset({
    'gameId', 'category', 'offerTitle', 'description', 'guaranteedDeliveryTime',
    'quantity', 'minQuantity', 'pricePerUnit', 'volumeDiscounts', 'hasOriginalEmail',
    'mainOfferImage', 'offerImages', 'tradeEnvironmentValues', 'attributes',
})
# These describe the response/lifecycle, not editable content of the PUT.
_READ_ONLY_FIELDS = frozenset({
    'id', 'userId', 'gameCategoryTitle', 'offerState', 'expireDate', 'offerVersion',
    'pricePerUnitWithDiscount', 'pricePerUnitInUSD', 'discountPercentage',
    'accountsDetails', 'accountDeliveryDetails',
})
_IMAGE_FIELDS = frozenset({'smallImage', 'largeImage', 'originalSizeImage'})


def _refuse(reason: str) -> None:
    # Never include provider values, credential text, or caught error messages.
    raise ValueError(reason) from None


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _identifier(value: Any) -> bool:
    return _nonblank(value) or (type(value) is int and value >= 0)


def _image(value: Any) -> bool:
    # An explicit empty object is the canonical "no main image" representation.
    # Nonempty triplets must be complete; do not synthesize missing image paths.
    return isinstance(value, dict) and (
        not value or (_IMAGE_FIELDS == value.keys()
                      and all(isinstance(value[key], str) for key in _IMAGE_FIELDS))
    )


def _validated_public_snapshot(live: Any) -> dict[str, Any]:
    if not isinstance(live, dict):
        _refuse('renewal_public_snapshot_invalid')
    if not _REQUIRED_PUBLIC_FIELDS <= live.keys():
        _refuse('renewal_public_fields_missing')
    # The flat response can contain read-only metadata. Unknown editable fields
    # cannot safely be assigned to a full PUT block: refuse rather than drop them.
    if live.keys() - _REQUIRED_PUBLIC_FIELDS - _READ_ONLY_FIELDS - {'tags'}:
        _refuse('renewal_public_fields_unrepresentable')
    raw = deepcopy(live)
    if not all(_nonblank(raw[key]) for key in (
        'offerTitle', 'guaranteedDeliveryTime', 'category',
    )) or not _identifier(raw['gameId']):
        _refuse('renewal_public_fields_invalid')
    # Category is the modeled string (e.g. "Account"), not an invented id object.
    if raw['description'] is not None and not isinstance(raw['description'], str):
        _refuse('renewal_public_fields_invalid')
    if any(type(raw[key]) is not int or raw[key] < 1 for key in ('quantity', 'minQuantity')):
        _refuse('renewal_public_fields_invalid')
    price = raw['pricePerUnit']
    if not isinstance(price, dict) or not {'amount', 'currency'} <= price.keys():
        _refuse('renewal_public_fields_missing')
    if price.keys() - {'amount', 'currency'}:
        _refuse('renewal_public_fields_unrepresentable')
    amount = price['amount']
    if type(amount) not in (int, float) or not _nonblank(price['currency']):
        _refuse('renewal_public_fields_invalid')
    try:
        wire_amount = float(amount)
    except (OverflowError, ValueError):
        _refuse('renewal_public_fields_invalid')
    if not math.isfinite(wire_amount) or wire_amount <= 0 or wire_amount != amount:
        _refuse('renewal_public_fields_invalid')
    if raw['hasOriginalEmail'] is not None and type(raw['hasOriginalEmail']) is not bool:
        _refuse('renewal_public_fields_invalid')
    if raw['mainOfferImage'] is not None and not _image(raw['mainOfferImage']):
        _refuse('renewal_public_fields_invalid')
    images = raw['offerImages']
    if images is not None and (
        not isinstance(images, list) or any(not _image(image) or not image for image in images)
    ):
        _refuse('renewal_public_fields_invalid')
    discounts = raw['volumeDiscounts']
    if discounts is not None and (
        not isinstance(discounts, list) or any(not isinstance(item, dict) for item in discounts)
    ):
        _refuse('renewal_public_fields_invalid')
    trade_envs = raw['tradeEnvironmentValues']
    if trade_envs is not None and not isinstance(trade_envs, list):
        _refuse('renewal_public_fields_invalid')
    if trade_envs:
        # The existing PUT builder represents exactly one environment id.
        if len(trade_envs) != 1:
            _refuse('renewal_public_fields_unrepresentable')
        env = trade_envs[0]
        if not isinstance(env, dict) or not _identifier(env.get('id')):
            _refuse('renewal_public_fields_invalid')
        if env.keys() - {'id', 'name', 'value'}:
            _refuse('renewal_public_fields_unrepresentable')
    attributes = raw['attributes']
    if attributes is not None and not isinstance(attributes, list):
        _refuse('renewal_public_fields_invalid')
    for attr in attributes or []:
        if not isinstance(attr, dict) or not {'id', 'value'} <= attr.keys() \
                or not _identifier(attr['id']):
            _refuse('renewal_public_fields_invalid')
        if attr.keys() - {'id', 'type', 'value', 'name'}:
            _refuse('renewal_public_fields_unrepresentable')
        value = attr['value']
        inferred_numeric = type(value) in (int, float)
        kind = attr.get('type', 'Numeric' if inferred_numeric else 'Select')
        if not isinstance(kind, str) or kind not in {'Numeric', 'Select'} \
                or (kind == 'Select' and inferred_numeric):
            _refuse('renewal_public_fields_unrepresentable')
        if kind == 'Numeric':
            if not inferred_numeric:
                _refuse('renewal_public_fields_invalid')
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                _refuse('renewal_public_fields_invalid')
        elif isinstance(value, dict):
            if not _identifier(value.get('id')):
                _refuse('renewal_public_fields_invalid')
            if value.keys() - {'id', 'name', 'value'}:
                _refuse('renewal_public_fields_unrepresentable')
        elif not _nonblank(value):
            _refuse('renewal_public_fields_invalid')
    if 'tags' in raw and (
        not isinstance(raw['tags'], list) or any(not isinstance(tag, str) for tag in raw['tags'])
    ):
        _refuse('renewal_public_fields_invalid')
    # Known full-PUT representations for explicitly absent optional content.
    # Missing fields were already refused, so these never fill model defaults.
    if raw['description'] is None:
        raw['description'] = ''
    return raw


def build_renewal_payload(live: dict[str, Any], credentials_response: Any) -> dict[str, Any]:
    """Return a full wire-compatible unchanged PUT, or a fixed local ValueError.

    No credentials are regenerated. Structured MFA/unknown delivery fields use
    the existing lossless helper, and live quantity must equal its entry count.
    Explicit null description becomes ''; null main image becomes {}; optional
    null arrays become []; empty volume discounts become null at the wire edge.
    Other public content must survive the established builder unchanged.
    """
    raw = _validated_public_snapshot(live)
    try:
        delivery = preserved_delivery_details(credentials_response)
    except (EldoradoDeliveryDetailsError, AttributeError, TypeError, ValueError):
        _refuse('renewal_delivery_details_unreadable')
    if len(delivery) != raw['quantity']:
        _refuse('renewal_delivery_quantity_mismatch')

    # Reuse the editor's pure builder without modifying manual/pool behavior.
    from apps.posting.services.offer_editor import build_eldorado_full_update_payload

    try:
        payload = build_eldorado_full_update_payload(SimpleNamespace(raw_data=raw), [])
        payload['accountDeliveryDetails'] = delivery
        # Tags are modeled public content not included in the older editor builder.
        if 'tags' in raw:
            payload['details']['tags'] = deepcopy(raw['tags'])
        wire = to_wire_payload(payload)
    except Exception:
        _refuse('renewal_payload_not_faithful')

    expected_details = {
        'pricing': {
            'quantity': raw['quantity'], 'minQuantity': raw['minQuantity'],
            'pricePerUnit': raw['pricePerUnit'],
            'volumeDiscounts': raw['volumeDiscounts'] or None,
        },
        'offerTitle': raw['offerTitle'], 'description': raw['description'],
        'guaranteedDeliveryTime': raw['guaranteedDeliveryTime'],
        'hasOriginalEmail': raw['hasOriginalEmail'] or False,
        'mainOfferImage': raw['mainOfferImage'] or {}, 'offerImages': raw['offerImages'] or [],
    }
    if 'tags' in raw:
        expected_details['tags'] = raw['tags']
    attrs = []
    for attr in raw['attributes'] or []:
        value = attr['value']
        kind = attr.get('type', 'Numeric' if type(value) in (int, float) else 'Select')
        attrs.append({'id': attr['id'], 'type': kind,
                      'value': value['id'] if isinstance(value, dict) else value})
    envs = raw['tradeEnvironmentValues'] or []
    expected_game = {
        'gameId': str(raw['gameId']), 'category': raw['category'],
        'tradeEnvironmentId': str(envs[0]['id']) if envs else None,
        'offerAttributes': attrs, 'attributeIdsCsv': None,
    }
    if wire.get('details') != expected_details or wire.get('augmentedGame') != expected_game \
            or wire.get('accountDeliveryDetails') != delivery or 'accountSecretDetails' in wire:
        _refuse('renewal_payload_not_faithful')
    return wire
