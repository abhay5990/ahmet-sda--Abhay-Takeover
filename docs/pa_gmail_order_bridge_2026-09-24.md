# PA Gmail Order-Report Bridge

**Date:** 2026-09-24  
**Scope:** Dedicated PlayerAuctions Mart mailbox order notifications routed from CodeTracker to SDA.  
**Status:** Implemented in source; disabled until the two protected deployment environments receive the same dedicated bridge secret and the SDA public HTTPS endpoint is verified.

## Verified inputs and boundary

CodeTracker reads only the dedicated `PA Orders` Gmail label under the existing Gmail OAuth connection. It accepts only the configured verified sender and supported Account-order notification format. It retains only the external PA order ID, visible tracking code, market, delivery mode, and Gmail observation time. It does not transfer the email body, recipients, credentials, marketplace links, Gmail token, or other mailbox data.

SDA receives a signed JSON event containing exactly those retained fields. The receiver validates the event ID, sender identity, HMAC signature, timestamp freshness, allowed field set, numeric order ID, and visible `#CODE` format. Events are idempotent by event ID. A CodeTracker event is acknowledged as `created`, `duplicate`, or `unmatched`; it never causes a marketplace API request, auto-delivery, cancellation, relisting, deletion, or browser/relay action.

## Inventory separation

The two inventories are deliberately isolated. CodeTracker first proves a notification code exists in its own durable code table before creating its own order report or performing Eldorado/GameBoost duplicate protection. CodeTracker-owned events are not sent to SDA. SDA independently matches only one active SDA Mart listing by the exact visible code and rejects the known CodeTracker game set: Fortnite, Valorant, League of Legends, and Rainbow Six. An event with no unique SDA listing is retained only as `unmatched` and has no operational side effect.

## Release validation

The CodeTracker signed-contract tests passed, including HTTPS-only configuration, signature tamper rejection, and cross-system code exclusion. The SDA Python syntax checks passed. The SDA contract tests passed with three tests; a Django deprecation warning about a future URLField default scheme was emitted but does not concern this bridge. The full SDA integration test suite still has an unrelated SQLite-incompatible historical migration, so production validation must use the actual MySQL deployment and a signed synthetic event after the secret and endpoint are configured.

## Activation and rollback

Activation requires an HTTPS SDA receiver URL and a newly generated shared secret stored only in protected service configuration for both systems. Before enabling the Settings toggle, verify the SDA route returns the expected authentication rejection for a request without a valid signature. Then enable forwarding in CodeTracker; only emails observed after that timestamp are eligible. Rollback is the CodeTracker **Pause SDA order sync** control, which immediately stops future event enqueueing and delivery attempts without touching Gmail or marketplace records.
