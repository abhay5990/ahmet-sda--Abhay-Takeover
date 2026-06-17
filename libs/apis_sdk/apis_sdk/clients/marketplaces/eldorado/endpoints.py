"""
Eldorado API endpoint constants.

Centralized URL paths for the Eldorado API.
"""


class EldoradoEndpoints:
    """Eldorado API endpoint paths."""

    # Offers
    CREATE_OFFER = "/api/flexibleOffers/account"
    UPDATE_OFFER = "/api/flexibleOffers/account/{offer_id}/details"
    DELETE_OFFER = "/api/flexibleOffersUser/me/{offer_id}"
    SEARCH_MY_OFFERS = "/api/flexibleOffers/me/search"
    GET_OFFER = "/api/flexibleOffers/{offer_id}"

    # Offer Details (credentials)
    GET_OFFER_DETAILS = "/api/offers/accountDetails/byOfferId/{offer_id}"
    GET_ORDER_DETAILS = "/api/offers/accountDetails/byOrderId/{order_id}"

    # Offer state
    OFFER_STATE_COUNTS = "/api/flexibleOffersUser/me/stateCount"

    # Orders
    MY_SELLER_ORDERS = "/api/orders/me/seller/orders/"
    GET_ORDER_BY_ID = "/api/orders/me/{order_id}"
    ORDER_STATES_COUNT = "/api/orders/me/statesCount"

    # Reviews
    SELLER_REVIEWS = "/api/orders/me/reviews"

    # Notifications
    NOTIFICATIONS_ME = "/api/notifications/me"

    # Images
    UPLOAD_IMAGE = "/api/files/me/Offer"

    @classmethod
    def offer(cls, offer_id: str) -> str:
        return cls.UPDATE_OFFER.format(offer_id=offer_id)

    @classmethod
    def delete_offer(cls, offer_id: str) -> str:
        return cls.DELETE_OFFER.format(offer_id=offer_id)

    @classmethod
    def offer_details(cls, offer_id: str) -> str:
        return cls.GET_OFFER_DETAILS.format(offer_id=offer_id)

    @classmethod
    def order_details(cls, order_id: str) -> str:
        return cls.GET_ORDER_DETAILS.format(order_id=order_id)

    @classmethod
    def order_by_id(cls, order_id: str) -> str:
        return cls.GET_ORDER_BY_ID.format(order_id=order_id)
