# U7Buy → SDA Automatic Account Delivery — verified contract (2026-10-12)

## Approved scope

The owner changed the U7Buy SDA scope from manual account delivery to **automatic account delivery** for owned Rust, GTA 5 Online, and Forza Horizon 6 accounts. This record covers only the official U7Buy Game Service Account Offer API. It does not authorize any marketplace write, account configuration, credential submission, webhook registration, or live offer creation.

## Verified official contract

- U7Buy Game Service Account offers expose per-SPU delivery choices through `deliveryVoList`. Each entry provides a `deliveryId` and a type/name; automatic delivery is an option only if it is present in that specific seller catalog/SPU response.
- The official `RemoteOfferManageUpdateGameServiceBo` create/update contract requires `deliveryType`, `inventory`, `stockPrice`, and `priceUsd`. For account offers, the docs state that **Automatic** delivery requires a `keys` array; each entry uses the documented `encrypted` field. The contract describes this as automatic account delivery information.
- The public API contract does not document a client-side encryption algorithm or a separate public key. SDA must not invent one. It will send the account bundle only in the documented `keys[].encrypted` field over the official HTTPS Basic-auth API, and will not record the bundle in database JSON, logs, errors, or public offer text.
- The official order API uses `Preparing` (`orderStatus=2`) as the seller-delivery state, `Delivering` (`3`), `To Receive` (`4`), `Completed` (`5`), and `Cancelled` (`6`). The documented manual order flow is delivery-parameter read, start-delivery, then completion. It is not used for automatic-key offers because the key is assigned with the offer.
- The public seller guide states that automatic delivery distributes the entered account credentials once the buyer places an order and that automatic listings undergo a platform verification process, normally up to 72 hours, before they become customer-visible.
- Webhook payloads contain only an event and order/offer identifiers. SDA must verify the documented HMAC over `AppId + ',' + raw request body`, accept the event durably, then use the official order-detail endpoint as the state authority.

## SDA release safeguards required

1. Fail closed unless each game mapping includes a catalog-verified automatic-delivery type ID and explicit `automatic_delivery_enabled: true`.
2. Accept automatic delivery only for owned, one-account stock. Reject dropship payloads and empty credential bundles.
3. Keep the public offer title and description credential-free. Put the account bundle only in `keys[].encrypted`.
4. Persist only safe metadata for an automatic offer (`delivery_mode`, key count); remove `keys` before `Listing.raw_data` or any audit serialization.
5. Treat an automatic U7Buy order linked to a managed automatic offer as instant at `Preparing` because credentials were already assigned. This permits existing exact-offer cross-market cleanup while never treating payment-verifying/payment-pending states as sold.
6. Preserve the existing `Completed`-only pool-consumption/replenishment rule for both manual and automatic U7Buy orders. Automatic U7Buy orders are marked instant at verified `Preparing` solely for exact-offer cross-market cleanup; they do not bypass the existing confirmed-sale pool rule.
7. Require a read-only seller catalog check to prove automatic delivery availability for each approved Rust/GTA/FH6 SPU before enabling configuration. Require separate owner approval before any first live offer write.

## References

[1]: https://openapi.u7buy.com/v2/docs/Models/RemoteOfferManageUpdateGameServiceBo.html "U7Buy Game Service Offer request model"
[2]: https://openapi.u7buy.com/v2/docs/Apis/GameServiceOfferApi.html "U7Buy Game Service Offer API"
[3]: https://openapi.u7buy.com/v2/docs/Apis/OrderManageApi.html "U7Buy Order Management API"
[4]: https://openapi.u7buy.com/v2/docs/Webhooks.html "U7Buy Webhook documentation"
[5]: https://www.u7buy.com/help-center/selling/how-to-upload-subscription-account-offers "U7Buy automatic delivery guide"
