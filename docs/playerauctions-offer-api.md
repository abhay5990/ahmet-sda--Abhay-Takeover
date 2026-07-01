# PlayerAuctions Offer API — Complete Reference

> Single-file technical reference for the PlayerAuctions **Seller / Offer API**.
> Intended to be given to an AI agent so it can understand and call the API correctly.
> Source: PlayerAuctions Help Center (OpenAPI section). Compiled 2026-07-01.

---

## 1. Overview

The Offer API lets a seller manage listings ("offers") programmatically and in real time:
create offers, edit pricing/inventory/expiration, hide/show, cancel, bulk-upload, and manage
listing images. It supports five product categories:

| Category      | `productType` value          | Create path suffix     |
| ------------- | ---------------------------- | ---------------------- |
| Currency      | `currency`                   | `/offers/currency`     |
| Items         | `items` / `item`             | `/offers/item`         |
| Accounts      | `accounts` / `account`       | `/offers/account`      |
| Boosting      | `powerleveling`              | `/offers/powerleveling`|
| Top Up        | `topup`                      | `/offers/topup`        |

**Design conventions**

- REST, resource-oriented URLs.
- Request bodies are JSON (except file uploads, which are `multipart/form-data`).
- Responses are JSON using a standard envelope (see §4).
- Standard HTTP verbs: `GET` (read), `POST` (create/action), `PUT` (update), `DELETE` (delete).

**Base URL**

```
https://seller-api.playerauctions.com
```

All endpoint paths below are relative to this base URL.

> Note: Some example URLs in responses reference a sandbox host (`www-sandbox.playerauctions.com`).
> Treat the base URL above as production. Confirm any sandbox host with PlayerAuctions if you need one.

---

## 2. Getting an API Key

1. **Request access** — Log in to PlayerAuctions and open the API Management page:
   `https://member.playerauctions.com/account/api-key-management`.
   Submit an "Application Reason" describing intended use, then wait for approval.
2. **Configure** — After approval: set an **API Name**, add at least one **whitelisted IP address**
   (only whitelisted IPs may call the API), then click **ADD API KEY**.
3. **Save credentials** — The **Secret Key** is shown **only once** at creation. Copy and store it
   securely (e.g. a secrets manager). If lost, you must delete the key and generate a new one.

You end up with two values:
- **API Key** (public identifier), e.g. `d7cbe9de312a83c255f1c8543f469695`
- **Secret Key** (private, used for signing), e.g. `pask_...`

---

## 3. Authentication & Request Signing

Every request must include three HTTP headers. Authentication uses **HMAC-SHA256** signing.

| Header           | Type      | Description                                                                                                   |
| ---------------- | --------- | ------------------------------------------------------------------------------------------------------------ |
| `X-PA-API-KEY`   | string    | Your API Key.                                                                                                 |
| `X-PA-TIMESTAMP` | timestamp | Unix time in **seconds**. Required on all requests. **Expires after 5 minutes.** Example: `1780293232`.      |
| `X-PA-SIGN`      | string    | HMAC-SHA256 signature computed from `apiKey + timestamp + requestBody` using your **Secret Key** (see below).|

### 3.1 Signature algorithm

```
canonicalString = apiKey + timestamp + requestBody
signature       = LOWER_HEX( HMAC_SHA256( key = secretKey, message = canonicalString ) )
```

- `requestBody` is the exact raw JSON body string you send.
- For **GET / DELETE** or empty-body requests, use an empty string (or, if the endpoint takes a
  JSON body, the exact body you send). Keep the string used for signing byte-identical to what is sent.
- **multipart/form-data endpoints** (e.g. `/api/v1/offers/bulk-upload`, image upload): the `requestBody`
  used for signing consists **only of the non-file form-field values**, and those values are
  **sorted alphabetically by field key** before concatenation. File contents are not part of the signature.
- Because the timestamp expires in 5 minutes, keep the client clock synchronized (NTP).

### 3.2 Reference implementations

**JavaScript (crypto-js)**
```javascript
const CryptoJS = require("crypto-js");

const secretKey   = "pask_jDOCvy7Ot4lTJNfGV3q78VPTXjl6Ms85GmY-Bc4wMKw"; // Secret Key
const apiKey      = "d7cbe9de312a83c255f1c8543f469695";                  // API Key
const timestamp   = String(Math.floor(Date.now() / 1000));               // seconds
const requestBody = JSON.stringify({ offerId: 15000 });                  // exact body sent

const canonicalString = apiKey + timestamp + requestBody;
const signature = CryptoJS.HmacSHA256(canonicalString, secretKey).toString(CryptoJS.enc.Hex);

// headers:
// X-PA-API-KEY: apiKey
// X-PA-TIMESTAMP: timestamp
// X-PA-SIGN: signature
```

**C#**
```csharp
string apiKey      = "d7cbe9de312a83c255f1c8543f469695";
string timestamp   = "1780293232";
string requestBody = "{ \"offerId\": 15000 }";
string secretKey   = "pask_jDOCvy7Ot4lTJNfGV3q78VPTXjl6Ms85GmY-Bc4wMKw";

string canonicalString = $"{apiKey}{timestamp}{requestBody}";

using (var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(secretKey)))
{
    byte[] hash = hmac.ComputeHash(Encoding.UTF8.GetBytes(canonicalString));
    string signature = BitConverter.ToString(hash).Replace("-", "").ToLower();
}
```

**PHP**
```php
function generateSignature($apiKey, $timestamp, $requestBody, $secretKey) {
    $canonicalString = $apiKey . $timestamp . $requestBody;
    return hash_hmac('sha256', $canonicalString, $secretKey);
}
$signature = generateSignature($apiKey, $timestamp, $requestBody, $secretKey);
```

---

## 4. Response Envelope & Errors

### 4.1 Success envelope

```json
{
  "code": 10000,
  "message": "Operation Successful.",
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "data": { }
}
```

| Field       | Type   | Meaning                                                           |
| ----------- | ------ | ---------------------------------------------------------------- |
| `code`      | int    | `10000` = success. Any other value = error.                     |
| `message`   | string | Human-readable message / error detail.                          |
| `requestId` | string | Unique request id. Log it; include it when contacting support.  |
| `data`      | object | Payload (shape depends on endpoint). Absent/`{}` for some ops.  |

### 4.2 Error codes

Codes are 5 digits; the first digit is the category:
`1xxxx` parameter, `2xxxx` signature, `3xxxx` auth, `4xxxx` business, `5xxxx` server.

| Code  | Name                | Category       | Meaning / typical cause                                         | Handling                                              |
| ----- | ------------------- | -------------- | -------------------------------------------------------------- | ---------------------------------------------------- |
| 10000 | Success             | Success        | OK.                                                            | Proceed.                                             |
| 10001 | MissingHeader       | Parameter      | A required header is missing.                                  | Include all 3 auth headers.                          |
| 10002 | InvalidParameter    | Parameter      | Missing/wrong-typed/invalid parameter.                        | Validate against this spec; fix the request.         |
| 20001 | InvalidSignature    | Signature      | Signature mismatch: wrong secret, clock skew, malformed sign. | Re-check signing, sync clock (5-min window).         |
| 30001 | AuthenticationError | Authentication | Invalid/expired credentials.                                  | Verify API key/secret; regenerate if needed.         |
| 30002 | AuthrizationError   | Authorization  | No permission for this resource/action.                       | Check account permissions / seller level.            |
| 40001 | BusinessError       | Business       | Business rule violated (status, duplicate, etc.).             | Read `message`; adjust request.                      |
| 50001 | InternalServerError | Server Error   | Unexpected server error.                                      | Retry after short delay; if persists, contact support with `requestId`. |

Extra codes seen in specific endpoints: `40001` (also used for "seller level insufficient", e.g. bulk template download).

---

## 5. Recommended Agent Workflow

To create an offer safely:

1. `GET /api/v1/offers/creation-prevalidation` — confirm the account is a seller and which product
   types it may upload (`isAllowCurrencyUpload`, `isAllowItemUpload`, `isAllowAccountUpload`).
2. `GET /api/v1/games` — resolve `gameId` (and check flags like `isMCurrencyType`, `isCDKeyRequired`).
3. Resolve category/server IDs for the target product type:
   - Servers/factions: `GET /api/v1/games/{id}/{type}/servers`
   - Currency types (if `isMCurrencyType`): `GET /api/v1/games/{id}/currencytypes`
   - Item categories: `GET /api/v1/games/{id}/items/categories`
   - Boosting categories: `GET /api/v1/games/{id}/powerleveling/categories`
   - Top-up categories: `GET /api/v1/games/{id}/topup/categories`
   - Delivery times: `GET /api/v1/games/{id}/{type}/deliveryTimes` (use `customId` for `deliveryGuarantee`)
4. (Optional) Upload an image: `POST /api/v1/media/images` → use returned `sasUri` as `screenShot`.
5. Create: `POST /api/v1/offers/{category}` with the correct body.
6. Manage later: list, edit, hide/show, cancel.

`{type}` in path templates is one of: `currency`, `items`, `accounts`, `powerleveling`, `topup`.

---

## 6. Base Data (Metadata) Endpoints

These are read-only lookups used to build valid offer payloads.

### 6.1 Game List
`GET /api/v1/games` — all supported games. No parameters.

Key `data[]` fields: `gameId`, `gameName`, `seoName`, `curName`, `curSuffix`,
`productType` (comma list of allowed types), `isSecurityQARequired` (1/0),
`isCDKeyRequired` (1/0), `isParentalPswRequired` (1/0), `isInvolveExploitsGame` (bool),
`isMCurrencyType` (bool — if true, `currencyTypeId` is required when creating a Currency offer).

```json
{
  "code": 10000, "message": "", "requestId": "…",
  "data": [
    {
      "gameId": 3637, "gameName": "League of Legends", "seoName": "LOL",
      "curName": "Riot Points", "curSuffix": "K",
      "productType": "currency,item,account,powerleveling,topup",
      "isSecurityQARequired": 0, "isCDKeyRequired": 0, "isParentalPswRequired": 0,
      "isInvolveExploitsGame": false, "isMCurrencyType": false
    }
  ]
}
```

### 6.2 Query Game Servers
`GET /api/v1/games/{id}/{type}/servers`

Path: `id` (game id, int, required), `type` (product type, required).
Returns a tree of server categories; each node: `id`, `productType`, `name`, `seoName`,
`parentId`, `itemSuffix`, `sequence`, `subCategorys[]` (same shape; may contain factions).
Use these `id` values for `serverId` and `categoryId` in offer creation.

### 6.3 Query Game Currency Types
`GET /api/v1/games/{id}/currencytypes`

Path: `id` (game id). Returns `data[]` of `{ currencyTypeId, currencyName }`.
Required only when the game has `isMCurrencyType = true`.

### 6.4 Query Item Categories
`GET /api/v1/games/{id}/items/categories`

Path: `id` (game id). Returns nested categories: `id`, `productType` (`Items`/`SubItems`),
`name`, `seoName`, `parentId` (0 = top level), `itemSuffix`, `sequence`, `subCategorys[]`.
For item offers you build `itemPath` as `rootItemId|itemId` (e.g. `290|1243`).

### 6.5 Query Boosting Categories
`GET /api/v1/games/{id}/powerleveling/categories`

Path: `id` (game id). Returns `data[]`: `id`, `name`, `parentId` (0 = root),
`isLastCategory` (bool), `sequence`, `subCategorys[]`.
Use for `parentItemId` (and optional `itemId`) in boosting offers.

### 6.6 Query Top Up Categories
`GET /api/v1/games/{id}/topup/categories`

Path: `id` (game id). Returns `data[]`:
`categoryId`, `categoryName`, `deliveryType` (1 = UID, 2 = Manual Top-Up),
`deliveryTypeName`, `quantityType` (1 = Fix, 2 = Flexible),
`quantities[]` of `{ id, fixQuantity, bonusQuantity }`.
Use `categoryId` for `topUpCategoryId` and `deliveryType` for `deliveryType`.

### 6.7 Query Game Delivery Time
`GET /api/v1/games/{id}/{type}/deliveryTimes`

Path: `id` (game id), `type` (product type).
Returns `data[]`: `customId`, `time`, `convertToHour`, `unit`
(`Minutes`/`Hour`/`Hours`/`Days`), `isEnable`.
**Use the `customId` value for the `deliveryGuarantee` field** when creating/editing offers.

---

## 7. Offer Creation Prevalidation

`GET /api/v1/offers/creation-prevalidation` — no parameters.

Response `data`: `memberId`, `status`, `memberClass`, `sellerLevel`,
`isAllowCurrencyUpload` (bool), `isAllowItemUpload` (bool), `isAllowAccountUpload` (bool),
`isWarningTipSanctions` (bool), `isSeller` (bool).

> Best practice: call this before any create call to confirm eligibility and avoid submission errors.

---

## 8. Create Offer Endpoints

Common create-response `data`: `offerId`, `navigateURL`, `title`, `productType`,
`gameName`, `productName`, `screenShot`, `imageBlacklist` (empty string = not blacklisted).
`offerDuration` allowed values everywhere: **3, 7, 14, 30** (days).
`agreeCheck` must be `true` (agreement to the Secure Seller Delivery Agreement).

### 8.1 Create Currency Offer
`POST /api/v1/offers/currency`

```json
{
  "gameId": 9479,
  "title": "this is a simple title",
  "offerDesc": "<p>this is a simple description</p>",
  "offerDuration": 30,
  "agreeCheck": true,
  "price": 5,
  "serverId": 9485,
  "categoryId": 9698,
  "instruction": "this is a simple instruction.",
  "deliveryGuarantee": 5,
  "totalUnit": 100,
  "minUnitPerOrder": 1,
  "currencyPerUnit": 100,
  "currencyTypeId": null,
  "discounts": [
    { "startPrice": 10, "discountRate": 2 },
    { "startPrice": 20, "discountRate": 4 },
    { "startPrice": 50, "discountRate": 8 }
  ]
}
```

| Field                       | Type    | Req | Notes                                                                       |
| --------------------------- | ------- | --- | -------------------------------------------------------------------------- |
| `gameId`                    | int     | Yes |                                                                            |
| `price`                     | decimal | Yes | Price per unit.                                                            |
| `offerDuration`             | int     | Yes | 3/7/14/30.                                                                 |
| `agreeCheck`                | bool    | Yes | Only `true`.                                                              |
| `title`                     | string  | Yes |                                                                            |
| `offerDesc`                 | string  | No  | HTML allowed.                                                             |
| `minUnitPerOrder`           | int     | Yes |                                                                            |
| `totalUnit`                 | int     | Yes |                                                                            |
| `currencyPerUnit`           | int     | Yes |                                                                            |
| `currencyTypeId`            | int     | No* | Required only if game `isMCurrencyType`. From `/games/{id}/currencytypes`. |
| `instruction`               | string  | No  |                                                                            |
| `deliveryGuarantee`         | int     | Yes | `customId` from delivery-times endpoint.                                   |
| `categoryId`                | int     | Yes | From `/games/{id}/{type}/servers`.                                         |
| `serverId`                  | int     | Yes | From `/games/{id}/{type}/servers`.                                         |
| `discounts[]`               | array   | No  | Volume discounts.                                                          |
| `discounts[].startPrice`    | int     | Yes | (within discounts)                                                        |
| `discounts[].discountRate`  | int     | Yes | (within discounts)                                                        |

### 8.2 Create Item Offer
`POST /api/v1/offers/item`

```json
{
  "gameId": 3637,
  "title": "Offer Title",
  "offerDesc": "<p>Offer Description</p>",
  "offerDuration": 30,
  "agreeCheck": true,
  "price": 5,
  "serverId": 3638,
  "categoryId": 3638,
  "instruction": "this is an instruction.",
  "deliveryGuarantee": 4,
  "totalUnit": 2000,
  "minUnitPerOrder": 1,
  "discounts": [
    { "startPrice": 10, "discountRate": 1 },
    { "startPrice": 50, "discountRate": 2 },
    { "startPrice": 100, "discountRate": 5 }
  ],
  "rootItem": 290,
  "itemId": 1243,
  "otherItem": "",
  "itemsPerUnit": 10,
  "screenShot": "https://cdn-image.azureedge.net/…/xxx.png",
  "itemPath": "290|1243"
}
```

| Field                | Type    | Req | Notes                                            |
| -------------------- | ------- | --- | ------------------------------------------------ |
| `gameId`             | int     | Yes |                                                  |
| `title`              | string  | Yes |                                                  |
| `offerDesc`          | string  | No  |                                                  |
| `offerDuration`      | int     | Yes | 3/7/14/30.                                       |
| `agreeCheck`         | bool    | Yes | Only `true`.                                    |
| `price`              | decimal | Yes |                                                  |
| `serverId`           | int     | Yes | From servers endpoint.                           |
| `categoryId`         | int     | Yes | From servers endpoint.                           |
| `instruction`        | string  | No  |                                                  |
| `deliveryGuarantee`  | int     | Yes | `customId` from delivery-times.                  |
| `totalUnit`          | int     | Yes |                                                  |
| `minUnitPerOrder`    | decimal | Yes |                                                  |
| `discounts[]`        | array   | No  | Same shape as currency.                          |
| `rootItem`           | int     | Yes | Top-level item category id.                      |
| `itemId`             | int     | Yes | Item (sub-category) id.                          |
| `otherItem`          | string  | No  | Custom item name.                                |
| `itemsPerUnit`       | decimal | Yes |                                                  |
| `screenShot`         | string  | No  | Image URL (from image upload).                   |
| `itemPath`           | string  | Yes | Format `rootItemId|itemId`, e.g. `290|1243`.     |

### 8.3 Create Account Offer
`POST /api/v1/offers/account`

Has two modes controlled by `isAuto`. When `isAuto=false` provide a `manual` object;
when `isAuto=true` provide an `autoDelivery` object.

**Manual delivery (`isAuto=false`)**
```json
{
  "gameId": 3637,
  "serverId": 4144,
  "categoryId": 4144,
  "price": 99.99,
  "selleraftersaleprotection": 30,
  "offerDuration": 30,
  "title": "Simple Title",
  "offerDesc": "<p>Simple Description.</p>",
  "screenShot": "https://cdn-image.azureedge.net/…/xxx.png",
  "agreeCheck": true,
  "isAuto": false,
  "manual": {
    "loginName": "loginName",
    "retypeLoginName": "loginName",
    "choose1": true,
    "choose2": true,
    "choose3": true,
    "choose4": true,
    "choose5": true,
    "deliveryGuarantee": 5
  }
}
```

**Auto delivery (`isAuto=true`)**
```json
{
  "gameId": 3637,
  "serverId": 4144,
  "categoryId": 4144,
  "price": 99.99,
  "selleraftersaleprotection": 30,
  "offerDuration": 30,
  "title": "Simple Title",
  "offerDesc": "<p>Simple Description.</p>",
  "screenShot": "https://cdn-image.azureedge.net/…/xxx.png",
  "agreeCheck": true,
  "isAuto": true,
  "autoDelivery": {
    "loginName": "loginName",
    "retypeLoginName": "loginName",
    "password": "123password",
    "retypePassword": "123password",
    "characterName": "CharacterName",
    "firstCDKey": "example-key",
    "isInfoSame": true,
    "original": { "firstName": "John", "lastName": "Doe", "phone": "0123456789", "email": "test@example.com", "city": "Shanghai", "country": "China" },
    "current":  { "phone": "0123456789", "email": "test@example.com", "city": "Shanghai", "country": "China" },
    "choose5": true,
    "instruction": "Extra instruction.",
    "securityQuestion": "SecurityQuestion",
    "securityAnswer": "Answer",
    "retypeSecurityAnswer": "Answer",
    "parentalPassword": "password123"
  }
}
```

Top-level fields: `gameId` (Yes), `categoryId` (Yes), `serverId` (Yes), `price` (Yes),
`sellerAfterSaleProtection` (Yes; days: 0/7/14/30 — note the request example uses lowercase
`selleraftersaleprotection`), `offerDuration` (Yes; 3/7/14/30), `title` (Yes), `offerDesc` (No),
`screenShot` (No), `agreeCheck` (Yes, only `true`), `isAuto` (Yes).

`manual.*` (required when `isAuto=false`): `loginName`, `retypeLoginName`,
`choose1` (knows parental password), `choose2` (knows registered phone),
`choose3` (has access to registered email), `choose4` (knows owner first/last name),
`choose5` (knows security-question answer; set `true` if none) — all `choose*` accept only `true` —
and `deliveryGuarantee` (`customId` from delivery-times).

`autoDelivery.*` (required when `isAuto=true`): `loginName`, `retypeLoginName`, `password`,
`retypePassword`, `characterName` (opt), `firstCDKey` (required if game `isCDKeyRequired`),
`isInfoSame`, `original.{firstName,lastName,phone,email,city,country}`,
`current.{phone,email,city,country}`, `choose5`, `instruction` (opt),
`securityQuestion`, `securityAnswer`, `retypeSecurityAnswer`, `parentalPassword`.

### 8.4 Create Boosting Offer (Powerleveling)
`POST /api/v1/offers/powerleveling`

```json
{
  "gameId": 3637,
  "title": "Simple Title",
  "offerDesc": "<p>Simple Description</p>",
  "offerDuration": 30,
  "agreeCheck": true,
  "price": 99.99,
  "totalUnit": 100,
  "parentItemId": 516,
  "itemId": ""
}
```

| Field           | Type    | Req | Notes                                              |
| --------------- | ------- | --- | -------------------------------------------------- |
| `gameId`        | int     | Yes |                                                    |
| `price`         | decimal | Yes |                                                    |
| `offerDuration` | int     | Yes | 3/7/14/30.                                         |
| `agreeCheck`    | bool    | Yes | Only `true`.                                      |
| `title`         | string  | Yes |                                                    |
| `offerDesc`     | string  | No  |                                                    |
| `totalUnit`     | int     | Yes |                                                    |
| `parentItemId`  | int     | Yes | Parent category id (from boosting categories).     |
| `itemId`        | int?    | No  | Sub-item id; optional when only one category level.|

### 8.5 Create Top Up Offer
`POST /api/v1/offers/topup`

```json
{
  "gameId": 3637,
  "title": "Simple Title",
  "offerDesc": "<p>Simple Description.</p>",
  "offerDuration": 30,
  "agreeCheck": true,
  "price": 5,
  "serverId": 3638,
  "categoryId": 3638,
  "instruction": "Simple Instruction.",
  "deliveryGuarantee": 6,
  "totalUnit": 2000,
  "minUnitPerOrder": 10,
  "currencyPerUnit": 10,
  "topUpCategoryId": 102,
  "deliveryType": 1
}
```

| Field               | Type    | Req | Notes                                              |
| ------------------- | ------- | --- | -------------------------------------------------- |
| `gameId`            | int     | Yes |                                                    |
| `price`             | decimal | Yes |                                                    |
| `offerDuration`     | int     | Yes | 3/7/14/30.                                         |
| `agreeCheck`        | bool    | Yes | Only `true`.                                      |
| `title`             | string  | Yes |                                                    |
| `offerDesc`         | string  | No  |                                                    |
| `minUnitPerOrder`   | decimal | Yes |                                                    |
| `totalUnit`         | int     | Yes |                                                    |
| `currencyPerUnit`   | decimal | Yes |                                                    |
| `instruction`       | string  | No  |                                                    |
| `deliveryGuarantee` | int     | Yes | Delivery guarantee (from delivery-times).          |
| `categoryId`        | int     | Yes | From servers endpoint.                             |
| `serverId`          | int     | Yes | From servers endpoint.                             |
| `topUpCategoryId`   | int     | Yes | `categoryId` from top-up categories endpoint.      |
| `deliveryType`      | int     | Yes | 1 = UID, 2 = Manual Top-Up.                        |

---

## 9. Edit Offer Endpoints

Editing mirrors creation: **same path, method `PUT`, same body plus an `offerId`.**

| Category | Endpoint (PUT)                 | Body |
| -------- | ------------------------------ | ---- |
| Currency | `PUT /api/v1/offers/currency`      | Create-Currency body + `offerId` |
| Items    | `PUT /api/v1/offers/item`          | Create-Item body + `offerId` |
| Accounts | `PUT /api/v1/offers/account`       | Create-Account body + `offerId` |
| Boosting | `PUT /api/v1/offers/powerleveling` | Create-Boosting body + `offerId` |
| Top Up   | `PUT /api/v1/offers/topup`         | Create-TopUp body + `offerId` |

Worked example — **Edit Currency Offer** (`PUT /api/v1/offers/currency`):
```json
{
  "offerId": 71394132,
  "gameId": 9479,
  "title": "this is a simple title",
  "offerDesc": "<p>this is a simple description</p>",
  "offerDuration": 30,
  "agreeCheck": true,
  "price": 5,
  "serverId": 9485,
  "categoryId": 9698,
  "instruction": "this is a simple instruction.",
  "deliveryGuarantee": 5,
  "totalUnit": 100,
  "minUnitPerOrder": 1,
  "currencyPerUnit": 100,
  "currencyTypeId": null,
  "discounts": [ { "startPrice": 10, "discountRate": 2 } ]
}
```
Response `data` shape matches the create response (`offerId`, `navigateURL`, `title`, …).

---

## 10. Query Single Offer Endpoints

Read one offer's full detail by id.

| Category | Endpoint (GET)                        |
| -------- | ------------------------------------- |
| Currency | `GET /api/v1/offers/currency/{id}`        |
| Items    | `GET /api/v1/offers/item/{id}`            |
| Accounts | `GET /api/v1/offers/account/{id}`         |
| Boosting | `GET /api/v1/offers/powerleveling/{id}`   |
| Top Up   | `GET /api/v1/offers/topup/{id}`           |

Path param: `id` (offer id, int, required).

Worked example — **Query Currency Offer** (`GET /api/v1/offers/currency/{id}`) response `data`:
```json
{
  "minUnitPerOrder": 1.0, "totalUnit": 100, "currencyPerUnit": 100.0,
  "instruction": "simple instruction", "deliveryGuarantee": 5,
  "discounts": [ { "startPrice": 10.0, "discountRate": 2.0 } ],
  "categoryId": 6590, "currencyTypeId": 0, "serverId": 6590,
  "gameId": 3637, "price": 5.0, "offerDuration": 30,
  "title": "Simple Title", "offerDesc": "<p>Simple Description</p>",
  "offerId": 71394132, "memberId": 678694,
  "state": 1, "productType": "currency"
}
```
`state`: **0 = closed, 1 = active, 3 = hidden**. Other categories return their respective
create/edit fields plus `offerId`, `memberId`, `state`, `productType`.

---

## 11. Offer Management Endpoints

### 11.1 Offer List
`GET /api/v1/offers` — paginated list of your offers.

Query params (all optional): `keyword` (fuzzy title search), `listingStatus`
(`active`/`hidden`/`closed`, default `active`), `productType`
(`all`/`currency`/`items`/`accounts`/`powerleveling`/`topup`, default `all`),
`serverId` (int), `factionId` (int; ignored if `serverId` given), `gameId` (int),
`pageIndex` (int), `pageSize` (int).

Response `data`: `hideOfferWarning` (string; non-empty explains why offers are hidden),
`count` (int), `items[]`. Each item includes: `offerId`, `systemStatus`, `offerStatus`,
`title`, `gameName`, `deliveryGuarantee`, `totalPrice`, `expiredTimeString`, `productType`,
`url`, plus type-specific fields: currency → `currencyPerUnit`, `everyGold`, `suffix`, `name`;
item → `itemNameEn`; top-up → `topUpFixQuantity`, `topUpExtraQuantity`, `topUpCategoryName`.

### 11.2 Cancellation Eligibility
`POST /api/v1/offers/cancellation-eligibility` — check whether offers can be cancelled.

```json
{
  "offerIds": [1001, 1002],
  "isAll": false,
  "parameters": {
    "keywords": "gold",
    "listingStatus": "active",
    "productType": "currency",
    "gameId": 1,
    "serverId": 10,
    "factionId": 5
  }
}
```
Body: `isAll` (bool, Yes). If `false`, `offerIds` (int[]) is required and `parameters` ignored.
If `true`, `offerIds` ignored and offers are selected by `parameters` filters
(`keywords`, `listingStatus`, `productType`, `gameId`, `serverId`, `factionId`;
`serverId` overrides `factionId`).

### 11.3 Set Offer Display Status
`POST /api/v1/offers/display-status` — hide or show offers.

```json
{
  "offerIds": [1001, 1002, 1003],
  "flag": "hide",
  "isAll": false,
  "parameters": { "keywords": "gold", "listingStatus": "active", "productType": "currency", "gameId": 1, "serverId": 10, "factionId": 5 }
}
```
Body: `flag` (Yes; `hide` or `display`, case-insensitive), `isAll` (Yes),
`offerIds` (required when `isAll=false`), `parameters` (filters when `isAll=true`, same as above).

### 11.4 Cancel Offer
`POST /api/v1/offers/cancel` — permanently cancel offers.

```json
{
  "offerIds": [1001, 1002],
  "isAll": false,
  "parameters": { "keywords": "gold", "listingStatus": "active", "productType": "currency", "gameId": 1, "serverId": 10, "factionId": 5 }
}
```
Same `isAll` / `offerIds` / `parameters` semantics as above.
Recommended flow: call **Cancellation Eligibility** first, then **Cancel Offer**.

---

## 12. Bulk Offer Upload

### 12.1 Download Bulk Template
`GET /api/v1/offers/bulk-template` — download the template / reference lists as `.xlsx`.

Query params: `productType` (Yes; `currency`/`items`/`accounts`),
`fileType` (Yes; `template`, `serverlist`, `currencytypelist` [currency],
`itemlist` [items], `emaildomains` [accounts]).
Returns an Excel file. Errors: `40001` (seller level insufficient), `10002` (invalid parameter).
Bulk tooling is only available to sellers with appropriate permissions.

### 12.2 Bulk Offer Upload
`POST /api/v1/offers/bulk-upload` — `multipart/form-data`.

Form fields: `file` (Yes; the filled `.xlsx`), `productType` (Yes; `currency`/`items`/`accounts`).
Remember the multipart signing rule (§3.1): sign only non-file fields, sorted by key.

Response `data`: `offerTotalCount`, `offers[]` with
`offerId`, `serverName`, `offerTitle`, `offerTitleUrl`, `offerPrice`, `offerPriceUnit`.

### 12.3 Query Uploaded Offers
`GET /api/v1/offers/bulk-upload` — results of prior bulk uploads.

Query params: `pageIndex` (int, opt), `pageSize` (int, opt),
`productType` (Yes; `currency`/`items`/`accounts`).
Response `data`: `count`, `items[]` (same fields as bulk-upload `offers[]`).

---

## 13. Image Gallery Management

### 13.1 Upload Image
`POST /api/v1/media/images` — `multipart/form-data`.

Form fields: `file` (Yes; image), `type` (No; `title` or `description`, default `title`),
`gameId` (Yes).
Response `data`: `blobName`, `sasUri` (use this as `screenShot` in offers),
`created`, `length`, `verified`.

### 13.2 Query Gallery
`GET /api/v1/media/images` — list uploaded images.

Query param: `gameId` (Yes).
Response `data`: `totalSize`, `images[]` with `blobName`, `sasUri`, `created`, `length`, `verified`.

### 13.3 Delete Image
`DELETE /api/v1/media/images`

```json
{ "blobName": "image1.jpg" }
```
Body: `blobName` (Yes). Success returns the standard envelope with no `data` payload.

---

## 14. Quick Endpoint Index

| Method | Path                                          | Purpose                         |
| ------ | --------------------------------------------- | ------------------------------- |
| GET    | `/api/v1/games`                               | List games                      |
| GET    | `/api/v1/games/{id}/{type}/servers`           | Servers/factions tree           |
| GET    | `/api/v1/games/{id}/currencytypes`            | Currency types                  |
| GET    | `/api/v1/games/{id}/items/categories`         | Item categories                 |
| GET    | `/api/v1/games/{id}/powerleveling/categories` | Boosting categories             |
| GET    | `/api/v1/games/{id}/topup/categories`         | Top-up categories               |
| GET    | `/api/v1/games/{id}/{type}/deliveryTimes`     | Delivery time options           |
| GET    | `/api/v1/offers/creation-prevalidation`       | Seller eligibility              |
| POST   | `/api/v1/offers/currency`                     | Create currency offer           |
| PUT    | `/api/v1/offers/currency`                     | Edit currency offer             |
| GET    | `/api/v1/offers/currency/{id}`                | Query currency offer            |
| POST   | `/api/v1/offers/item`                         | Create item offer               |
| PUT    | `/api/v1/offers/item`                         | Edit item offer                 |
| GET    | `/api/v1/offers/item/{id}`                    | Query item offer                |
| POST   | `/api/v1/offers/account`                      | Create account offer            |
| PUT    | `/api/v1/offers/account`                      | Edit account offer              |
| GET    | `/api/v1/offers/account/{id}`                 | Query account offer             |
| POST   | `/api/v1/offers/powerleveling`                | Create boosting offer           |
| PUT    | `/api/v1/offers/powerleveling`                | Edit boosting offer             |
| GET    | `/api/v1/offers/powerleveling/{id}`           | Query boosting offer            |
| POST   | `/api/v1/offers/topup`                        | Create top-up offer             |
| PUT    | `/api/v1/offers/topup`                        | Edit top-up offer               |
| GET    | `/api/v1/offers/topup/{id}`                   | Query top-up offer              |
| GET    | `/api/v1/offers`                              | List offers                     |
| POST   | `/api/v1/offers/cancellation-eligibility`     | Check cancel eligibility        |
| POST   | `/api/v1/offers/display-status`               | Hide/show offers                |
| POST   | `/api/v1/offers/cancel`                       | Cancel offers                   |
| GET    | `/api/v1/offers/bulk-template`                | Download bulk template          |
| POST   | `/api/v1/offers/bulk-upload`                  | Bulk upload offers              |
| GET    | `/api/v1/offers/bulk-upload`                  | Query bulk-uploaded offers      |
| POST   | `/api/v1/media/images`                        | Upload image                    |
| GET    | `/api/v1/media/images`                        | Query image gallery             |
| DELETE | `/api/v1/media/images`                        | Delete image                    |

---

## 15. Agent Implementation Notes

- **Always send all three auth headers**; missing any → `10001`. Signature errors → `20001`.
- **Clock sync matters**: timestamp is valid for 5 minutes.
- **Sign the exact bytes you send.** Don't re-serialize the JSON differently after signing.
- **Multipart signing** excludes files; include only other form fields, sorted alphabetically by key.
- **IP whitelisting**: calls must originate from a whitelisted IP.
- **Resolve IDs first** (game → servers/categories → delivery times) before creating offers.
- **`deliveryGuarantee`** takes the `customId` from the delivery-times endpoint, not raw minutes.
- **`agreeCheck` must be `true`** or the create/edit call fails.
- **Multi-currency games** (`isMCurrencyType=true`) require `currencyTypeId` on currency offers.
- **Log `requestId`** from every response for troubleshooting/support.
- **Edit = Create body + `offerId` via `PUT`**; **Query single = `GET /{type}/{id}`**.
- Endpoint sub-pages for Edit/Query of Item, Account, Boosting, Top Up follow the same
  request/response shapes as their Create counterparts (plus `offerId`); verify field-level
  requiredness against the live docs if an edit call is rejected.

---

*Compiled from the official PlayerAuctions Help Center OpenAPI articles. PlayerAuctions warns
against unauthorized third-party APIs — use only official credentials and the official base URL.*
