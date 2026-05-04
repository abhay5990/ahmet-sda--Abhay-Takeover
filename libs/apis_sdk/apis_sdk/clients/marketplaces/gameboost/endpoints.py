"""
GameBoost API endpoint constants.

Centralized URL paths for the GameBoost v2 API.
"""


class GameBoostEndpoints:
    """GameBoost API endpoint paths."""

    # Account Offers
    ACCOUNT_OFFERS = "/account-offers"
    ACCOUNT_OFFERS_CREATE = "/account-offers/create"

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

    @classmethod
    def account_offer_list_action(cls, account_id: str) -> str:
        """POST /account-offers/{account_id}/list — publish offer"""
        return f"{cls.ACCOUNT_OFFERS}/{account_id}/list"

    @classmethod
    def account_offer_unlist_action(cls, account_id: str) -> str:
        """POST /account-offers/{account_id}/draft — unlist offer"""
        return f"{cls.ACCOUNT_OFFERS}/{account_id}/draft"

    @classmethod
    def account_offer_duplicate(cls, account_id: str) -> str:
        """POST /account-offers/{account_id}/duplicate"""
        return f"{cls.ACCOUNT_OFFERS}/{account_id}/duplicate"

    @classmethod
    def account_offer_template(cls, game_slug: str) -> str:
        """GET /account-offers/templates/{game_slug}"""
        return f"{cls.ACCOUNT_OFFERS}/templates/{game_slug}"

    @classmethod
    def order_messages(cls, order_id: str) -> str:
        """GET/POST /account-orders/{order_id}/messages"""
        return f"{cls.ACCOUNT_ORDERS}/{order_id}/messages"

    @classmethod
    def order_credentials(cls, order_id: str) -> str:
        """PATCH /account-orders/{order_id}/credentials"""
        return f"{cls.ACCOUNT_ORDERS}/{order_id}/credentials"

    # ------------------------------------------------------------------
    # Item Offers
    # ------------------------------------------------------------------
    ITEM_OFFERS = "/item-offers"

    @classmethod
    def item_offer(cls, offer_id: str) -> str:
        return f"{cls.ITEM_OFFERS}/{offer_id}"

    @classmethod
    def item_offer_list_action(cls, offer_id: str) -> str:
        """POST /item-offers/{offer_id}/list — publish offer"""
        return f"{cls.ITEM_OFFERS}/{offer_id}/list"

    @classmethod
    def item_offer_unlist_action(cls, offer_id: str) -> str:
        """POST /item-offers/{offer_id}/draft — unlist offer"""
        return f"{cls.ITEM_OFFERS}/{offer_id}/draft"

    @classmethod
    def item_offer_archive_action(cls, offer_id: str) -> str:
        """POST /item-offers/{offer_id}/archive"""
        return f"{cls.ITEM_OFFERS}/{offer_id}/archive"

    @classmethod
    def item_offer_template(cls, game_slug: str) -> str:
        """GET /item-offers/templates/{game_slug}"""
        return f"{cls.ITEM_OFFERS}/templates/{game_slug}"

    @classmethod
    def item_offer_orders(cls, offer_id: str) -> str:
        """GET /item-offers/{offer_id}/orders"""
        return f"{cls.ITEM_OFFERS}/{offer_id}/orders"

    # ------------------------------------------------------------------
    # Item Orders
    # ------------------------------------------------------------------
    ITEM_ORDERS = "/item-orders"

    @classmethod
    def item_order(cls, order_id: str) -> str:
        return f"{cls.ITEM_ORDERS}/{order_id}"

    @classmethod
    def item_order_complete(cls, order_id: str) -> str:
        """POST /item-orders/{order_id}/complete"""
        return f"{cls.ITEM_ORDERS}/{order_id}/complete"

    @classmethod
    def item_order_messages(cls, order_id: str) -> str:
        """GET/POST /item-orders/{order_id}/messages"""
        return f"{cls.ITEM_ORDERS}/{order_id}/messages"

    # ------------------------------------------------------------------
    # Gift Card Catalog
    # ------------------------------------------------------------------
    GIFT_CARDS = "/gift-cards"
    GIFT_CARD_BRANDS = "/gift-cards/brands"
    GIFT_CARD_REGIONS = "/gift-cards/regions"

    @classmethod
    def gift_card(cls, gift_card_id: str) -> str:
        """GET /gift-cards/{gift_card_id}"""
        return f"{cls.GIFT_CARDS}/{gift_card_id}"

    # ------------------------------------------------------------------
    # Gift Card Offers
    # ------------------------------------------------------------------
    GIFT_CARD_OFFERS = "/gift-cards/offers"

    @classmethod
    def gift_card_offer(cls, offer_id: str) -> str:
        """GET/PATCH/DELETE /gift-cards/offers/{offer_id}"""
        return f"{cls.GIFT_CARD_OFFERS}/{offer_id}"

    @classmethod
    def gift_card_offer_stock(cls, offer_id: str) -> str:
        """POST /gift-cards/offers/{offer_id}/stock — add stock"""
        return f"{cls.GIFT_CARD_OFFERS}/{offer_id}/stock"

    @classmethod
    def gift_card_offer_stock_item(cls, offer_id: str, delivery_id: str) -> str:
        """DELETE /gift-cards/offers/{offer_id}/stock/{delivery_id}"""
        return f"{cls.GIFT_CARD_OFFERS}/{offer_id}/stock/{delivery_id}"

    # ------------------------------------------------------------------
    # Gift Card Orders
    # ------------------------------------------------------------------
    GIFT_CARD_ORDERS = "/gift-card-orders"

    @classmethod
    def gift_card_order(cls, order_id: str) -> str:
        """GET /gift-card-orders/{order_id}"""
        return f"{cls.GIFT_CARD_ORDERS}/{order_id}"

    # ------------------------------------------------------------------
    # Currency Offers
    # ------------------------------------------------------------------
    CURRENCY_OFFERS = "/currency-offers"

    @classmethod
    def currency_offer(cls, offer_id: str) -> str:
        """GET/PATCH /currency-offers/{offer_id}"""
        return f"{cls.CURRENCY_OFFERS}/{offer_id}"

    @classmethod
    def currency_offer_list_action(cls, offer_id: str) -> str:
        """POST /currency-offers/{offer_id}/list — publish offer"""
        return f"{cls.CURRENCY_OFFERS}/{offer_id}/list"

    @classmethod
    def currency_offer_unlist_action(cls, offer_id: str) -> str:
        """POST /currency-offers/{offer_id}/draft — unlist offer"""
        return f"{cls.CURRENCY_OFFERS}/{offer_id}/draft"

    @classmethod
    def currency_offer_archive_action(cls, offer_id: str) -> str:
        """POST /currency-offers/{offer_id}/archive"""
        return f"{cls.CURRENCY_OFFERS}/{offer_id}/archive"

    @classmethod
    def currency_offer_template(cls, game_slug: str) -> str:
        """GET /currency-offers/templates/{game_slug}"""
        return f"{cls.CURRENCY_OFFERS}/templates/{game_slug}"

    @classmethod
    def currency_offer_orders(cls, offer_id: str) -> str:
        """GET /currency-offers/{offer_id}/orders"""
        return f"{cls.CURRENCY_OFFERS}/{offer_id}/orders"

    # ------------------------------------------------------------------
    # Currency Orders
    # ------------------------------------------------------------------
    CURRENCY_ORDERS = "/currency-orders"

    @classmethod
    def currency_order(cls, order_id: str) -> str:
        """GET /currency-orders/{order_id}"""
        return f"{cls.CURRENCY_ORDERS}/{order_id}"

    @classmethod
    def currency_order_complete(cls, order_id: str) -> str:
        """POST /currency-orders/{order_id}/complete"""
        return f"{cls.CURRENCY_ORDERS}/{order_id}/complete"

    @classmethod
    def currency_order_messages(cls, order_id: str) -> str:
        """GET/POST /currency-orders/{order_id}/messages"""
        return f"{cls.CURRENCY_ORDERS}/{order_id}/messages"
