# PR47 renewal safety and main-only rollout

Owner approval on 6 November 2026 covers safety fixes, tests and an exact-head merge into `abhay5990/ahmet-sda--Abhay-Takeover` main only. It does not authorize deployment, production migration application, service restart, automatic renewal enablement, marketplace trials, delivery or cached expiry backfill. MCT, other marketplaces, game ownership and image generation are unchanged.

## Admission and scope

The unified `sync.renew_expiring_listings` flag requires an explicitly enabled row with a nonempty `value.providers` list containing only supported provider names. Enablement and provider selection are read together. Missing rows, invalid configuration and database failures hold execution rather than defaulting to both marketplaces. The legacy PA-only flag retains its previous admission semantics. When the explicit unified scope includes PA, the scheduler, manual command and final durable Mart helper agree; Eldorado-only scope cannot admit PA.

Both renewal commands accept a lead window of 1–96 hours. A separately approved exact-offer trial must identify a genuinely eligible offer and its current ownership/sale state, not expand the lead window to bypass eligibility. The earlier proposed 720-hour PA trial is not valid.

## Eldorado update boundary

The corrected renewal takes the shared same-store, same-offer lease before authoritative private reads and keeps it through delivery reads, the governed one-shot PUT and expiry verification. Shared lease keys normalize case/whitespace, so uppercase UUIDs in the unchanged editor cannot select a different lock from the renewal. Existing general PUT retries and normal read behavior remain unchanged outside this specialized renewal path.

Private-offer models retain a deep-copied, transient raw offer snapshot before Pydantic parsing can round prices, coerce Boolean quantities or discard nested keys. That snapshot is a private attribute excluded from model dumps and representation; it is not added to database audit payloads. Renewal accepts only complete validated raw public content, never model defaults or a selective overlay onto cached listing data. Missing required fields, lossy or malformed prices, unknown image/pricing fields, mismatched quantity and unreadable delivery entries refuse the update. Explicit nulls follow the canonical wire representation without restoring stale description/images. Structured delivery entries, including MFA and unknown credential fields, are preserved.

Private, delivery and verification reads select a renewal-only single-attempt execution path rather than the general retry executor that logs raw provider exhaustion text. Real SDK logger-sentinel tests verify provider read messages do not reach that logger. The specialized PUT executes once, including authentication rejection: it does not refresh and replay the PUT. Other executor callers retain their old authentication-refresh behavior.

One potentially sent PUT counts against the write budget even if the response is uncertain. Private, delivery and verification calls count against the explicit read budget. Insufficient reads refuse before sending. Unclassified exceptions stop the run. These counters describe the guarded offer workflow, not all authentication infrastructure or external actor traffic.

## Durable unresolved state

A sanitized account/offer-scoped renewal-cycle claim commits before credentials are read or a possible send. A crash leaves it pending. A portable nullable unconditional unique `unresolved_key` prevents competing account/offer aliases or changed-expiry cycles from holding two unresolved slots; this does not rely on partial uniqueness unsupported by MySQL. The slot is retained on pending, unknown and unproven outcomes and cleared only on a verified terminal or locally proven pre-send outcome. The separate unique cycle key remains historical replay protection.

Unknown/unproven outcomes never become retry tickets after six hours, across dates or local aliases. Remote error strings and arbitrary external no-write labels are not proof of safe retry. Successful verification requires the same Active offer, an expiry later than the previous value and a future expiry no more than 60 days away. Fresh local ownership and sale/order state is checked again before send and finalization; stale rows are not revived after a sale or reassignment.

The sanitized observation ledger's admin view is read-only, with no add, edit, delete, bulk action or retry escape. Resolving an uncertain send requires a separately approved reconciliation workflow. No credentials, raw delivery content, provider payload or raw error text belongs in that ledger.

## Validation and future deployment

The combined synthetic suite ran **267 tests**, passing with **two SQLite row-lock concurrency skips**. An additional SDK compatibility run passed **68 tests** (including specialized boundary tests already present in the combined suite), and **13 existing editor/refill tests** passed. Django checks, compilation, sync migration consistency and isolated static collection passed. Do not add these counts as unique cases: the specialized SDK cases overlap.

The corrected `sync.0013` migration is schema-only; automatic cached expiry backfill is removed. The candidate reader can inspect unknown expiries with bounded reads. No migration is applied to production by this main-only release. Validation uses synthetic in-memory database state and mocked marketplace transport; it is not live multi-process MySQL contention proof, exclusion of external marketplace sales or proof of successful live renewal.

A future deployment needs separate owner authorization, current host rules, a tested exact revision, zero durable active work before stopping services, controlled migration/build/restart and live revision/health verification. Preserve effective Eldorado write holds and PA renewal-disabled state unless separately approved. A successful main merge is not deployment or enabled automation. Readiness and code tests are not live marketplace proof.

Validation and release scope are recorded in `todo-pr47-safety-20261106.md`.
