# SDA PR46 safety release — 5 November 2026

Owner: Abhay. Priority: High. Approval: fix blockers, test, merge and deploy SDA PR46. Scope is PA Mart exact-ID pre-expiry renewal, durable unknown outcomes, verified expiry, exact eligible clone ownership and historical native-order correlation. No marketplace trial, renewal flag enablement, MCT change, Shop change or broad reconciliation is authorized by this release.

Baseline: author head `7ad7ac951d19ffb56878428ee910fc650ffe031d`; main/live rollback point `83e8e4f9b2a41506fdbe7ad2180a2ef5aeb785b7`, branch `production/pr45-held`. Fresh preflight confirmed all three SDA services active, all work queues zero, Eldorado writes held, PA renewal flag false, PA create hold false unchanged.

## Verified fixes

Scheduler, manual command and direct helper require an explicitly enabled renewal flag and fail closed on absent flags/read failures. Mart has no legacy renewal fallback. The durable per-cycle ledger commits a pending identity before transport; pending/unknown—including crashes and next-day runs—do not auto-resend. Verified expiry must be aware, future, bounded and newer than the prior expiry. Missing/invalid/elapsed/unextended expiry is unknown, never invented success.

The service locks and checks exact ACTIVE clone/PUSHED item/live-owner/product/lane/pool relationships and current/historical order, sale, Gmail, dispatch, edit and fault evidence. Replacement updates affect only the exact listing, clone and item, without allocation/status changes. Completed immutable ledger records preserve all account-scoped old/new offer identities for delayed native orders; ambiguous aliases refuse attribution. Pending-payment Mart events cannot reach linked stock sale signals. Raw responses, credential data and arbitrary external errors are not retained in the ledger.

A read-only Django admin view exposes pending/unknown/rejected/succeeded renewal state, safe identifiers and local reason codes. It has no add, edit, delete or retry permission. This is scoped operational observability, not a new external monitoring service or notification automation.

## Validation and release gates

| Gate | Result |
|---|---|
| Corrected focused suite | 166 tests run: 165 passed, one DB row-lock concurrency test skipped on SQLite |
| Included coverage | 38 core renewal and 34 identity tests; gate/provider tests; existing Mart, stock, signed Gmail and historical sale regressions |
| Syntax / diff | Passed |
| Independent final safety review | PASS, no concrete held-deployment blocker |
| Production settings / static collection | Passed using isolated source and protected runtime configuration |
| Sync migration consistency | No changes detected |
| Pending production migration | Only `sync.0012_pa_mart_renewal_attempt` |
| Production row-lock capability | Verified available; not a live contention test |
| Exact-head merge, zero-work deployment, live health/revision | Pending execution after this tested source commit |

Preserve all existing effective service flags, untracked environment backups/reports and zero-work gates. Apply only the new sanitized ledger migration. Restart all three SDA services because shared order/provider code loads in those processes. Never infer live marketplace renewal success from synthetic tests or enablement from a code deployment.

Remaining limits: local locks are not a remote sale lease or global allocator; live database contention and MCT/PA renewal proof remain unverified. Unknown/pending requires separate owner-authorized reconciliation; no automatic retries or expired-key recycling. Safe GraphMemory was unavailable; the previously sensitive graph remains unused. Authoritative evidence remains current Git, runtime flags, schema and tests.
