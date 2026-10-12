# U7Buy → SDA Account Integration — 2026-10-12

## Owner and scope

- **Owner:** SDA development
- **Priority:** High
- **Scope:** One U7Buy seller account; Rust, GTA 5 Online, and Forza Horizon 6 account offers only.
- **Excluded:** Existing listing migration, MCT U7Buy/SAB flows, and any marketplace write during validation.
- **Owner change (2026-10-12):** Automatic U7Buy account delivery is now in scope for newly created, owned one-account offers only. It remains disabled until each game has verified catalog configuration and the owner approves the first live offer write.

## Verified evidence

- U7Buy API documentation confirms one configured external webhook URL, HMAC-SHA256 webhook verification, catalog/SPU discovery, Game Service Account Offer writes, and order-detail lookups.
- Read-only live catalog discovery confirmed all three requested account games and their platform choices.
- `docs/u7buy_sda_api_evidence_20261012.md` contains redacted references and contract details.
- GraphMemory was not queried because the current host instruction marks the existing graphs as potentially sensitive and quarantined; source, tests, official docs, and live read-only catalog evidence are authoritative for this task.

## Delivery plan

- [x] Add the U7Buy provider/client with typed, sanitized responses; implement catalog discovery, offer create/read/update/off-sale, and order detail reads through the official Basic-auth API.
- [x] Add U7Buy as an SDA provider and an `IntegrationAccount` option, with encrypted credential storage and store/marketplace validation.
- [x] Add a U7Buy Game Service Account mapper and game/platform catalog cache for Rust, GTA 5, and Forza Horizon 6. Render title/description from SDA templates; keep each game/platform mapping separate.
- [x] Add one signed webhook ingress that dispatches U7Buy order and inventory events, verifies the documented HMAC over raw bytes, deduplicates events, fetches official order detail, and responds with `{"status":"OK"}` only after durable acceptance.
- [x] Add an idempotent, scoped U7Buy order consumer that records incoming orders, matches an exact U7Buy offer to an SDA listing/pool item, and consumes pool stock only after a provider-confirmed sale status.
- [x] Add fail-closed automatic-delivery support for newly created owned account offers. Automatic mode requires a seller-catalog-verified delivery ID, sends one account bundle only through U7Buy's `keys[].encrypted` field, rejects dropship/empty credentials, and removes `keys` before any SDA audit persistence.
- [x] Mark only locally tagged automatic U7Buy offers as instant on an authoritative order-detail read, allowing existing exact-offer cross-market cleanup while keeping legacy/manual U7Buy orders non-instant.
- [ ] Add U7Buy account-template defaults for Rust/GTA 5/Forza Horizon 6 and an admin/dashboard page containing connection status, live catalog refresh, mappings, webhook state, templates, and order/offer audit summaries.
- [x] Add migrations plus focused U7Buy provider, webhook, order-mapping, manual/automatic-delivery, and credential-redaction coverage. The focused suite passed; one unrelated existing Rust payload assertion still fails in the broad suite and was not changed.
- [x] Push the SDA source release to GitHub at `6c19e0782aae`.
- [ ] Deploy the automatic-delivery code only after zero active posting/sync work. Do not configure credentials or a webhook during the code release.
- [ ] Configure one seller account outside Git with verified Rust/GTA 5/Forza Horizon 6 mappings. Each automatic game mapping must set `delivery_mode=automatic`, `automatic_delivery_enabled=true`, and its exact catalog-derived `automatic_delivery_type_id`.
- [ ] Register the signed webhook and run a read-only production catalog/connection check. Obtain separate owner approval before the first automatic U7Buy offer creation.

## Release validation

1. Tests prove signature rejection, valid-event idempotency, U7Buy order-detail verification, and no stock consumption for unpaid/non-confirmed states.
2. U7Buy catalog values are loaded from the provider endpoint and validated against each selected game/platform mapping.
3. A dry-read validates API credentials and catalog access; **no offer is created, updated, delisted, or auto-delivered** during validation.
4. The initial production configuration is fail-closed until the U7Buy account, game mappings, templates, and public callback URL are entered and the connection passes a read-only check.
5. Automatic delivery records a redacted listing audit marker only. Raw `keys`/credential bundles must not appear in `Listing.raw_data`, logs, posting errors, webhook events, or public offer content.
