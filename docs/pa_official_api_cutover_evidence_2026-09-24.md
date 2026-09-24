# PlayerAuctions Official API Cutover Evidence

**Date:** 2026-09-24  
**Scope:** Mart offer-management migration from browser/relay authentication to the documented PlayerAuctions Offer API.

## Authoritative source

The PlayerAuctions **Offer API Documentation** describes an HMAC-SHA256 API for managing seller offers, available at `https://support.playerauctions.com/hc/en-us/articles/58370185051929-Offer-API-Documentation` (accessed 2026-09-24). The Account Offer Creation Flow is documented at `https://support.playerauctions.com/hc/en-us/articles/58505391972121-Account-Offer-Creation-Flow`.

The documented offer API includes offer creation, query, editing, list/search, hide/show, cancellation eligibility, cancellation, bulk upload/query, gallery upload/query/delete, and game/server/category/delivery-time metadata. Account offer creation requires creation prevalidation, game lookup, account server/category lookup, delivery-time lookup, then `POST /api/v1/offers/account`.

The published Offer API reference does **not** list seller-order list/detail, buyer messaging, manual delivery actions, order lifecycle, disputes, refunds, or payout operations. The Gmail bridge is therefore the verified replacement for new-order notification evidence only; it is not a substitute for undocumented order APIs.

## Verified MCT state

The CodeTracker live Mart release uses protected official credentials and signed official API calls for account-offer creation, exact-ID cancellation, and offer renewal. The renewal policy is four days before the locally recorded expiry and must query/reuse the full current offer payload before changing its duration. A live read-only account-offer creation preflight previously passed. The Gmail bridge has verified label-only polling and parses order ID and title tracking code from PA new-order notifications for Mart’s cross-market duplicate protection.

## Verified SDA code state before migration

SDA contains an official PA facade (`libs/apis_sdk/.../playerauctions_official`) and provider composite. Offer list/create/cancel/display/bulk/metadata are already routed to the official facade when API credentials are present. However, before this cutover:

- `backend/apps/posting/services/pool/replenisher.py` still retrieves relay tokens and posts replacement offers via `/pa-post-offer`.
- `backend/apps/posting/services/offer_editor.py` invokes browser-session edit logic and uses relay posting for pool edits.
- `backend/apps/integrations/providers/playerauctions.py` always builds a legacy browser/relay client alongside the official client whenever official credentials exist.
- Seller-order reads still route to the legacy client. SDA’s requested scope does not require an automatic deletion/order flow; this route must be disabled for Mart rather than silently retained.
- The existing renewal command uses an old delete-and-recreate path and a 72-hour default. This is not suitable for a safe official same-offer renewal.

## Safety boundary

Only Mart is in scope. Shop behavior and any separate Shop credentials/relay usage must remain unchanged. No source purchase, customer delivery, deletion automation, order processing, browser login, or fallback to unsupported legacy paths is authorized within this SDA migration.

## Completed implementation

The Mart official client is now constructed **without** a legacy browser client. This prevents the selected Mart account from obtaining a relay token, making browser-form edits, or polling browser-session orders. Shop and all other non-Mart accounts retain their existing lane.

| SDA operation | Mart implementation | Boundary |
|---|---|---|
| Create Account Offer | Signed official Account Offer create | Validated full account payload; no relay token or browser session |
| Pool replacement offer | Signed official Account Offer create | Per-item persistence; no relay batch route |
| Stock consumer batch | Sequential signed official Account Offer creates | A retryable provider failure is retained as unknown remote outcome |
| Single/pool offer edit | Signed official Account Offer edit | Full existing payload only; no cancel/recreate |
| Offer expiry renewal | Query → in-place edit → re-query | Default is **96 hours (four days)**; duration is set to 30 and a non-visible marker proves the re-query |
| Offer cancellation | Existing official cancellation support | Exact offer IDs only |
| Order sync/recovery | Explicitly disabled | The documented API has no seller-order endpoint; no relay fallback |

## Validation

- Python compilation passed for every changed SDA module.
- Focused isolated tests passed: **4 tests** covering official-only client isolation and Account Offer create/edit payload routing.
- The initial test run exposed an unrelated repository limitation: a MySQL-specific migration is not executable on SQLite. Re-running the focused suite with migrations disabled passed; production remains MySQL.
- No live offer creation, edit, cancellation, order recovery, relay login, or browser action was run during this validation.

## Deployment prerequisites and remaining unknowns

The SDA production host was not accessible through the currently authorized SSH path. The source cutover must therefore be deployed through the authorized SDA deployment workflow before it becomes active. The host needs the approved Mart official API key/secret in its protected credential record and the Mart store identifier mapped to the official-only lane. Run the scheduler dry run first, then verify one existing Mart offer renewal before relying on the four-day scheduled renewal. No source code or this record includes secrets, delivery credentials, raw API bodies, or browser/session data.
