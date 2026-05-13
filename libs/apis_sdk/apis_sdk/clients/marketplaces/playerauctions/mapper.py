"""
PlayerAuctions mapper.

Provides helpers for building PlayerAuctions API payloads from raw sync data.
The ``build_from_raw`` method converts the flat structure stored in
Listing.raw_data (sync source format) to the nested structure expected by
the PA ``create_offer`` API.

Password encryption is NOT handled here — the provider layer applies
``_encrypt_pa_passwords()`` before sending to the API.
"""

from __future__ import annotations

from typing import Any


class PlayerAuctionsMapper:
    """
    Mapper for PlayerAuctions API payloads.

    Implemented:
    - build_from_raw: converts sync raw_data → create_offer payload
    """

    @staticmethod
    def build_from_raw(raw_data: dict[str, Any]) -> dict[str, Any]:
        """Build a create_offer payload from raw PlayerAuctions sync data.

        Takes the structure stored in Listing.raw_data (sync format with
        ``details`` sub-dict from the offer detail API) and converts it to
        the flat structure expected by POST create_offer.

        Args:
            raw_data: Raw offer dict from PA sync (includes ``details`` key
                with autoDelivery, gameId, price, etc.).

        Returns:
            Ready-to-send payload dict for ``create_offer()``.
            Passwords are plain text — encryption is the caller's responsibility.
        """
        details = raw_data.get('details') or {}

        # --- pricing ----------------------------------------------------------
        price = details.get('price') or _parse_price_string(
            raw_data.get('total_price') or raw_data.get('totalPrice') or '0'
        )

        # --- game / category --------------------------------------------------
        game_id = details.get('gameId') or raw_data.get('gameId') or 0
        server_id = details.get('serverId') or details.get('server_id') or 0
        category_id = details.get('categoryId') or details.get('category_id') or server_id

        # --- delivery ---------------------------------------------------------
        is_auto = details.get('isAuto', False)
        auto_delivery_raw = details.get('autoDelivery') or {}

        auto_delivery: dict[str, Any] = {
            'loginName': auto_delivery_raw.get('loginName', ''),
            'retypeLoginName': auto_delivery_raw.get('loginName', ''),
            'password': auto_delivery_raw.get('password', ''),
            'retypePassword': auto_delivery_raw.get('password', ''),
            'characterName': auto_delivery_raw.get('characterName', ''),
            'isInfoSame': auto_delivery_raw.get('isInfoSame', True),
            'original': auto_delivery_raw.get('original') or {},
            'current': auto_delivery_raw.get('current') or {},
            'choose5': auto_delivery_raw.get('choose5', True),
            'instruction': auto_delivery_raw.get('instruction', ''),
            'securityQuestion': auto_delivery_raw.get('securityQuestion', ''),
            'securityAnswer': auto_delivery_raw.get('securityAnswer', ''),
            'retypeSecurityAnswer': auto_delivery_raw.get('retypeSecurityAnswer')
                or auto_delivery_raw.get('securityAnswer', ''),
            'parentalPassword': auto_delivery_raw.get('parentalPassword', ''),
            'firstCDKey': auto_delivery_raw.get('firstCDKey', ''),
        }

        # --- title / description ----------------------------------------------
        title = raw_data.get('title') or details.get('title') or ''
        description = (
            details.get('offerDesc')
            or details.get('description')
            or raw_data.get('description')
            or ''
        )

        # --- offer duration ---------------------------------------------------
        offer_duration = details.get('offerDuration') or 30

        return {
            'offerId': None,
            'gameId': int(game_id) if game_id else 0,
            'serverId': int(server_id) if server_id else 0,
            'categoryId': int(category_id) if category_id else 0,
            'price': round(float(price), 2),
            'freeInsurance': details.get('freeInsurance', 7),
            'offerDuration': offer_duration,
            'title': title,
            'offerDesc': description,
            'screenShot': details.get('screenShot', ''),
            'agreeCheck': True,
            'isAuto': is_auto,
            'autoDelivery': auto_delivery,
            'manual': details.get('manual') or {
                'loginName': '',
                'retypeLoginName': '',
                'choose1': None,
                'choose2': None,
                'choose3': None,
                'choose4': None,
                'choose5': None,
                'deliveryGuarantee': 4,
            },
            'actionType': '',
        }


def _parse_price_string(price_str: str) -> float:
    """Parse PA price string like '$190.00' to float."""
    cleaned = price_str.replace('$', '').replace(',', '').strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0
