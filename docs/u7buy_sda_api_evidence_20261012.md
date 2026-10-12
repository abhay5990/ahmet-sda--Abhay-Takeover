# U7Buy SDA Integration Evidence — 2026-10-12

## Scope

This redacted design record covers a **single U7Buy seller account** used by SDA for **Rust Accounts**, **GTA 5 Online Accounts**, and **Forza Horizon 6 Accounts**. It contains no credential, buyer, order, or account-delivery data.

## Verified seller catalog

Read-only live seller-catalog discovery on the listing worker confirmed these account categories and platform options:

| Game | U7Buy category | Observed platforms |
|---|---|---|
| Rust | Accounts | PC, Xbox, PS4, PS5 |
| GTA 5 | Accounts | PC, PS4, PS5, Xbox One, Xbox Series X/S |
| Forza Horizon 6 | Accounts | PC, Xbox, PS4, PS5 |

The catalog is intentionally retrieved at onboarding time and cached in SDA. IDs are not embedded in source because catalog values can change.

## Official API contract

Sources:

- https://openapi.u7buy.com/v2/docs/GetStarted.html
- https://openapi.u7buy.com/v2/docs/Apis/GameServiceOfferApi.html
- https://openapi.u7buy.com/v2/docs/Models/RemoteOfferManageUpdateGameServiceBo.html
- https://openapi.u7buy.com/v2/docs/Apis/OrderManageApi.html
- https://openapi.u7buy.com/v2/docs/Webhooks.html

Verified facts:

1. The production base URL is `https://openapi.u7buy.com/prod-api/` and API authentication is HTTP Basic with a base64 `AppId:AppSecret` value.
2. Game-service account offers use the Game Service Offer API: catalog list/detail, create, get detail, and update.
3. Account offer requests require game entity/SPU/business IDs, delivery type, inventory, stock price, and buyer price; platform/region/server and attributes come from the per-SPU detail contract.
4. U7Buy sends webhook POSTs for new orders, completed orders, stock threshold, and stock-out. A webhook success acknowledgement is HTTP 200 with `{"status":"OK"}`. Official documentation describes one configured webhook URL, so SDA should use **one verified ingress URL with internal order and inventory event handlers**, not attempt to register separate external URLs without evidence that the seller portal supports it.
5. The webhook signature is HMAC-SHA256 over `AppId + ',' + raw JSON request parameters`, using the App Secret and raw-hex output.
6. An order webhook carries only an order ID. SDA must retrieve order detail before any database action. Official order progression is To Pay (0), Payment Verifying (1), Preparing (2), Delivering (3), To Receive (4), Completed (5), Cancelled (6).

## Safety decisions

- Webhook acceptance is idempotent and stores only a sanitized event envelope, external IDs, and redacted outcome.
- Incoming callbacks do not immediately expose or post credentials.
- `Preparing` records the order but does not consume stock. Only provider-confirmed terminal/confirmed-sale statuses may trigger pool consumption.
- No auto-delivery is enabled in the initial release. A separate approved fulfillment contract is required before sending credentials or completing shipment through the U7Buy API.
- Existing Eldorado, GameBoost, PlayerAuctions, MCT U7Buy/SAB, and existing store wiring remain unchanged.

## Order and webhook validation addendum

- The seller detail endpoint is `GET /open-api/order/{orderId}` and the seller list endpoint is `GET /open-api/order/list`; both use the documented Basic-auth request path.
- The documented detail response includes the order and offer IDs, game/platform IDs, price, quantity, timestamp, provider status, delivery method, currency, and dispute fields. SDA will persist only the metadata needed for order audit and matching, never buyer-delivery parameters.
- **Confirmed-sale policy:** only provider order status `5` (**Completed**) may consume a pool item or trigger replenishment. States `0`–`4` include payment, preparation, delivery, and buyer confirmation and remain non-consuming; status `6` is cancelled.
- U7Buy retries failed callbacks five times (1, 2, 5, 10, and 20 minutes). SDA must durably deduplicate a sanitized event hash before triggering any sync.
- Initial delivery mode is **manual only**. The implementation must never send credentials or call the shipment start/completion endpoints without a separately approved fulfillment contract.
