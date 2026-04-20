"""Small shared utilities for posting services."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def serialize_response(data: Any) -> dict:
    """Safely serialize an API response (Pydantic model, dict, or other) to a plain dict."""
    if data is None:
        return {}
    if hasattr(data, 'model_dump'):
        return data.model_dump()
    if hasattr(data, 'dict'):
        return data.dict()
    if isinstance(data, dict):
        return data
    return {'_raw': str(data)}


def extract_title_from_payload(payload: dict, marketplace: str) -> str:
    """Extract the title that was actually sent to the marketplace.

    Eldorado nests it under details.offerTitle; others use top-level 'title'.
    """
    if marketplace == 'eldorado':
        return payload.get('details', {}).get('offerTitle', '')
    return payload.get('title', '')


def extract_currency_from_payload(payload: dict, marketplace: str) -> str:
    """Extract the currency from the payload sent to the marketplace.

    Only Eldorado carries an explicit currency; others default to USD.
    """
    if marketplace == 'eldorado':
        pricing = payload.get('details', {}).get('pricing', {})
        return pricing.get('pricePerUnit', {}).get('currency', 'USD')
    return 'USD'


def _response_to_dict(data: Any) -> dict:
    """Convert response data (Pydantic/dict/other) to a plain dict for field extraction."""
    if data is None:
        return {}
    if hasattr(data, 'model_dump'):
        return data.model_dump()
    if hasattr(data, 'dict'):
        return data.dict()
    if isinstance(data, dict):
        return data
    return {}


def extract_price_from_response(response_data: Any, marketplace: str) -> Decimal | None:
    """Extract the confirmed USD price from a marketplace API response.

    Returns None if the response doesn't carry a usable price.

    Gameboost:  data.price_usd.value  (converted to seller's USD)
    Eldorado:   pricePerUnitInUSD.amount  (flat response) or pricePerUnit.amount
    PA:         response only has offer_id — no price returned.
    """
    data = _response_to_dict(response_data)
    if not data:
        return None

    try:
        if marketplace == 'gameboost':
            inner = data.get('data', {})
            if isinstance(inner, dict):
                price_usd = inner.get('price_usd', {})
                if isinstance(price_usd, dict) and price_usd.get('value') is not None:
                    return Decimal(str(price_usd['value']))
        elif marketplace == 'eldorado':
            # Prefer pricePerUnitInUSD, fallback to pricePerUnit
            ppu = data.get('pricePerUnitInUSD') or data.get('pricePerUnit') or {}
            if isinstance(ppu, dict) and ppu.get('amount') is not None:
                return Decimal(str(ppu['amount']))
    except (InvalidOperation, TypeError, ValueError):
        pass

    return None


def extract_title_from_response(response_data: Any, marketplace: str) -> str:
    """Extract the confirmed title from a marketplace API response.

    Gameboost:  data.title
    Eldorado:   offerTitle (flat response)
    PA:         response only has offer_id — no title returned.
    """
    data = _response_to_dict(response_data)
    if not data:
        return ''

    if marketplace == 'gameboost':
        inner = data.get('data', {})
        if isinstance(inner, dict):
            return inner.get('title', '')
    elif marketplace == 'eldorado':
        return data.get('offerTitle', '')

    return ''


def extract_listing_id(response_data) -> str:
    """Extract the created offer's ID from a marketplace API response.

    Different marketplaces return the ID in different fields.
    Tries: id → offer_id → listing_id → data (nested dict).

    Supports both plain dicts and Pydantic models.
    """
    # Pydantic model → convert to dict
    if hasattr(response_data, 'model_dump'):
        response_data = response_data.model_dump()
    elif hasattr(response_data, 'dict'):
        response_data = response_data.dict()

    if isinstance(response_data, dict):
        for key in ('id', 'offer_id', 'listing_id', 'data'):
            val = response_data.get(key)
            if val is not None:
                if isinstance(val, dict):
                    return str(val.get('id', val.get('offer_id', '')))
                return str(val)
    return str(response_data)
