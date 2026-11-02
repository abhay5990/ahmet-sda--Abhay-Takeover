# SDA PR 44 — account-preservation release

Date: 2026-11-02 UTC. Owner: Abhay / Manus. Priority: High.

## Scope and authorization

Fix the verified PR 44 account-preservation blockers, test, merge to main, and deploy on SDA host 35.196.63.190 with Eldorado writes held. Do not lift the hold or perform any live marketplace trial without a new owner approval. Do not change MCT, PlayerAuctions credentials, renewal holds, unrelated pool records, or marketplace listings.

GraphMemory was previously quarantined for sensitive-data concerns and is not used for this release. Current source, synthetic tests, protected runtime configuration, and durable job queues are authoritative.

## Verified evidence

- Original PR head: `87b458db38770bf5fb96ddb9ce92e6401e0b51f2`.
- Preflight production revision: `a92949180ac3df1138e2a5e54a9eda7762886cb5`.
- All three SDA services active; posting jobs/items, dispatch attempts/reservations, and PA edits all zero at initial preflight.
- 78 active Eldorado pool links, all with locally low/unknown counts, share 925 pending unreserved items. This is local database state, not a verified remote inventory count.
- Synthetic reproduction demonstrated lost updates between concurrent read/merge/PUT operations despite governor write spacing.
- Synthetic response/text/wire conversion demonstrated loss of non-null structured MFA. Actual production occurrence and affected live accounts remain unknown; no live credentials were inspected.
- Original focused tests: 17 SDK, 14 contract, 6 backend passed. A wider Rust hours assertion failure reproduced unchanged on production baseline.

## Fixes and affected symbols

- `eldorado/governor.py`: cross-process same-offer lease, process/thread-safe reentrancy, mutation write hold, per-store spacing.
- `eldorado/models.py`, `delivery_details.py`: preserve original structured delivery data in memory; fail closed on unreadable inventory units or absent authoritative list shape.
- `pool/replenisher.py::_push_eldorado`: lease before fresh read through full PUT; preserve all existing fields; failed PUT cannot recreate/delete the original.
- `offer_editor.py::_edit_eldorado`: same lease and fresh lossless snapshot; never stale local credential fallback or automatic replacement on failed edit.
- Regression tests: multiprocessing overlap, held writes versus allowed reads, MFA/unknown-field preservation, unreadable-entry rejection, caller read/write lease, and failed-PUT preservation.

## Release gate

- [x] Owner approved blocker fixes and deployment with writes held.
- [x] Original scope and durable production queues inspected read-only.
- [x] Initial preservation/caller tests passed in an isolated SDA worktree using SQLite memory database; no live marketplace requests.
- [x] Final combined regressions: 58 SDK, 19 backend, 14 payload-contract tests passed; changed Python syntax and diff whitespace passed. SQLite model tests disabled legacy MySQL-only migrations and used an ephemeral test encryption key. Production migration state is checked separately.
- [ ] Commit fix to PR 44 branch; merge exact reviewed head into GitHub main.
- [ ] Validate merged main in isolated worktree; verify migration plan and production checks.
- [ ] Confirm fresh zero-active-work boundary; stop scheduler/dropship only at this boundary.
- [ ] Set `ELDORADO_WRITES_HELD=true` on Gunicorn, scheduler, and dropship unit drop-ins, with one shared governor directory.
- [ ] Fast-forward controlled production branch to exact merged main; preserve untracked backups/reports.
- [ ] Build static assets/checks, then restore all three services.
- [ ] Verify live revision, each process hold setting, normal web response, and synthetic held mutation returning locally with zero transport calls.
- [ ] Verify PA renewal flag remains disabled; record release and rollback in host AGENTS.

## Rollback and unknowns

Rollback source to the recorded pre-release revision at an idle boundary; retain the Eldorado hold. Existing deployment backups/reports must remain intact. Release does not authorize offer creation, edits, cancellation, deletion, retry, delivery, or credential submission. No real full PUT is proven by synthetic tests; a separately approved exact-offer trial remains required. The host-local lease does not coordinate external edits or MCT writes on another host.
