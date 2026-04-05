"""
G2G API endpoint constants.

Centralized URL paths for the G2G marketplace API.
"""


class G2GEndpoints:
    """G2G API endpoint paths."""

    # Offers
    CREATE_OFFER = "/offer"
    UPDATE_OFFER = "/offer/{offer_id}"
    DELETE_OFFER = "/offer/{offer_id}"

    # Auth
    REFRESH_TOKEN = "/user/refresh_access"

    @classmethod
    def offer(cls, offer_id: str) -> str:
        """URL path for a specific offer."""
        return f"/offer/{offer_id}"

    @classmethod
    def my_offers(cls, seller_id: str) -> str:
        """URL path for listing seller's offers."""
        return f"/offer/seller/{seller_id}/my_offers"
