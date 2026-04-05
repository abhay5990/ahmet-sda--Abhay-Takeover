"""
GameBoost API endpoint constants.

Centralized URL paths for the GameBoost v2 API.
"""


class GameBoostEndpoints:
    """GameBoost API endpoint paths."""

    # Account Offers
    ACCOUNT_OFFERS = "/account-offers"

    # Account Orders
    ACCOUNT_ORDERS = "/account-orders"

    @classmethod
    def account_offer(cls, account_id: str) -> str:
        return f"{cls.ACCOUNT_OFFERS}/{account_id}"

    @classmethod
    def account_order(cls, order_id: str) -> str:
        return f"{cls.ACCOUNT_ORDERS}/{order_id}"

    @classmethod
    def offer_credentials(cls, account_id: str) -> str:
        """GET /account-offers/{account_id}/credentials"""
        return f"{cls.ACCOUNT_OFFERS}/{account_id}/credentials"

    @classmethod
    def offer_credential(cls, account_id: str, credential_id: str) -> str:
        """Single credential: DELETE / PATCH /account-offers/{account_id}/credentials/{credential_id}"""
        return f"{cls.ACCOUNT_OFFERS}/{account_id}/credentials/{credential_id}"

    @classmethod
    def offer_credentials_bulk_delete(cls, account_id: str) -> str:
        """POST /account-offers/{account_id}/credentials/bulk-delete"""
        return f"{cls.ACCOUNT_OFFERS}/{account_id}/credentials/bulk-delete"
