# SDA PR47 safety fixes — main only

Owner: Abhay. Priority: High. Approved 6 November 2026: fix/test verified PR47 blockers and merge to SDA GitHub main only. No production deployment, production migration, flag enablement, service restart, marketplace trial or bulk expiry backfill. Existing production PA renewal remains disabled and Eldorado writes held.

Baseline PR head `6a8cad0bf221d1c233f5fb2e0fd3aef93fc0107c`; main/production `3a1f341663e16d7d5ac7cc00c9a91da2d91d6f76`. Safe GraphMemory unavailable; quarantined graph not queried. Current Git/API evidence, source and synthetic runtime checks are authoritative.

## Completed implementation

- Atomic explicit unified provider configuration and fail-closed lookup; consistent scheduler/manual/final Mart admission; 1–96 hour command bounds.
- Same-offer lease spans fresh private content, fresh ownership/sale checks, delivery reads, one-shot PUT and verification. Shared UUID lease identity is normalized across editor and renewer.
- Deep-copied private raw offer snapshot retained before model coercion, excluded from dumps/repr. Live-only faithful public payload; missing/null distinctions, price/type/unknown image/pricing guards, quantity integrity and structured MFA/credential preservation.
- Renewal-only safe single-attempt private/delivery GETs avoid raw retry-exhaustion logger messages. Specialized PUT opts out of all retries including auth rejection; other SDK read/PUT/executor defaults preserved.
- Committed pending cycle and portable unique unresolved account/offer slot before possible send; uncertain/crashed states never age out or resend across cycles/aliases. Fresh finalization never revives sold/reassigned rows. Sanitized read-only admin view; no retry escape.
- Explicit logical read/possible-write accounting and stop-on-unknown/unclassified exception. Schema-only sync.0013, no automatic cached bulk backfill.
- MCT, other marketplaces, game and image behavior untouched.

## Verified tests and checks

- Combined corrected suite: 267 tests run, OK with 2 SQLite row-lock concurrency skips.
- Additional real SDK compatibility: 68 passed. Specialized SDK cases overlap the combined suite; do not sum as unique cases.
- Existing editor/refill compatibility: 13 passed.
- Actual private-response model negatives refuse bool quantities, rounded large prices and unknown pricing/image fields before PUT; real SDK logger sentinels do not escape safe reads; auth/transport/server failures send at most once; mixed-case UUIDs contend on the same lease.
- Django checks, compilation, sync makemigrations consistency and isolated static collection passed. Portable key schema is unconditionally unique, not partial.
- Tests ran only in detached isolated SDA worktree with synthetic in-memory DB and mocked transport. No live marketplace or production data action. Production source remains baseline with service flags/holds unchanged in fresh preflight.

## Release gate and limits

Push only the exact tested safety head to existing PR branch; refuse on concurrent head/main changes; merge with exact expected head and verify main tree equals tested source tree. Main-only release must not deploy or apply migrations.

SQLite tests do not prove MySQL live multi-process contention; host-local leases do not exclude remote marketplace actors. No successful live renewal claimed. Separate owner approval and fresh evidence required for deployment, enabling flags, unknown-send reconciliation or an exact-offer live trial. Documented rollout: docs/pr47_renewal_safety_20261106.md.

Implementation/tests complete; exact-head push and merge pending at commit preparation.
