# SDA PR45 safety release — 2026-11-04

Owner: Abhay. Priority: High. Scope: SDA Django PR45 only; no MCT, Shop, GameBoost, source-market, credential or marketplace operations.

Approval: fix/test verified blockers, then merge and deploy. Preserve existing Eldorado write holds and PA renewal hold. New expiry recovery must stay disabled where complete unsold evidence, common sale/allocation coordination, and scoped reuse are unavailable.

- [x] Review exact PR head and collect fresh production revision, services and zero-work evidence.
- [x] Reproduce incomplete-snapshot recycling and mismatched-product-link deletion using synthetic rows only.
- [x] Replace expiry writes with unbypassable read-only diagnostics; preserve late-sale product links.
- [x] Add exact ownership, protected-stock, signed-event and pagination diagnostics.
- [x] Require verified provider success; generic rejected/ambiguous external outcomes remain unknown without retry.
- [x] Permit no-write receipts only for locally generated pretransport refusals; never trust an external proof claim.
- [x] Fence Mart failures and unsubmitted claims against exact claim token and durable in-progress attempt.
- [x] Run 69 isolated regressions, including the real SDK local-refusal round trip, signed-sale guards, stale claim/attempt fencing and safe request-ID persistence. Django checks and compilation pass.
- [x] Independent safety review approved the held design except a stringified-None predicate; that predicate is corrected and covered by the passing real-SDK test. Production settings checks pass, migration plan is empty, row-lock capability is present, and the PA renewal flag remains false.
- [ ] Push tested PR head, merge exact head to main, verify merged scope.
- [ ] Deploy exact merged source at zero-active-work boundary; preserve untracked files and all existing holds.
- [ ] Verify live services, source revision, login health and unchanged holds; record release.

Validation limit: model-level tests use isolated SQLite with historical MySQL-only migrations disabled. They prove fencing state checks and stale-response refusal, not live multi-process MySQL contention. Because this release contains no expiry return transition, the unsafe sale/return race and shared-pool reuse path are unavailable rather than assumed safe.

Known remaining functionality: automatic return of expired keys is intentionally unavailable until authoritative complete sold/order coverage, immutable sale-resolution linkage, a common ownership lock and safe lane-scoped reuse contract are implemented and validated. This release does not enable bulk relisting, retry HTTP marketplace writes, or repair prior manual state changes.

Rollback: pre-release production/pr44-held at d9c899c96ac5b94e4079ad550dd21eef1d2652ef. Preserve the effective Eldorado hold. GraphMemory was not available via a safe authenticated connector; prior sensitive graph remains unused.
