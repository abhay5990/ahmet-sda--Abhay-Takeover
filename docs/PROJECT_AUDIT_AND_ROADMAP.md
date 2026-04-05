# Project Audit and Roadmap

Last updated: 2026-03-23

## Purpose

This document is the living source of truth for:

- current project structure
- documentation hygiene decisions
- long-term architecture direction
- implementation order for the next refactor steps

It is intentionally based on the current codebase, not on older migration-era plans.

---

## Current Code Truth

The current Django app boundaries are:

- `apps.accounts` - auth and user access
- `apps.inventory` - `Category`, `Game`, `OwnedProduct`, `DropshipProduct`
- `apps.integrations` - `IntegrationAccount`, `IntegrationCredential`, provider wrappers
- `apps.listings` - local listing state and listing lifecycle
- `apps.orders` - local order state and order lifecycle
- `apps.sync` - raw ingestion, checkpoints, run logs, sync orchestration
- `apps.dashboard` - UI views

Important current facts:

- `apps.sync` now exists and owns `RawPayload`, `SyncCheckpoint`, `SyncRun`, and the `sync_orders` command skeleton.
- External provider access already lives under `apps.integrations.providers`.
- Internal canonical term is `listing`, not `offer`.
- Listing ownership currently uses `ListingOwnedProduct` M2M.
- Order and listing lifecycle rules are implemented with Django signals.
- There is no visible test suite implementation yet; `tests/unit`, `tests/integration`, and `tests/e2e` are empty.
- Background execution is not implemented yet; Celery exists only in old planning docs.

---

## Documentation Audit

### Keep and maintain

- `README.md`
  - Keep as onboarding and local setup document.
  - Update wording so it describes what exists today vs what is planned.
- `_ai/spec.md`
  - Keep as high-level product scope.
- `_ai/decisions.md`
  - Keep as ADR log.
- `_ai/todo.md`
  - Keep only if it continues to be maintained after each major work session.
- `_data_samples/`
  - Keep as provider development input.
- `_helpers_folders/old_system_refferances/INVENTORY_MODELS_EXPORT.md`
  - Keep as historical schema reference only.

### Removed or retired from active use

- `django-migration-docs/ARCHITECTURE.md`
- `django-migration-docs/MIGRATION_TASKS.md`
- `django-migration-docs/USECASES.md`
- `django-migration-docs/HANDOFF_PROMPT.md`

Reason:

- these documents described migration-era target structures that no longer match the current repo state
- they created multiple competing architecture narratives inside the repo
- the active replacements now live under `docs/`

### Historical but still present

- `_ai/integrations_migration_plan.md`

Reason:

- it still contains useful transition reasoning
- but it should not drive new implementation decisions directly

### Remove or archive later

- `_ai/chatgpt_prompt.md`

Reason:

- this is a tool-specific meta prompt, not project documentation
- it duplicates information already present in `README.md`, `_ai/spec.md`, and `_ai/decisions.md`

### Corrected in this cleanup slice

- `_ai/architecture.md`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/IMPLEMENTATION_PHASES.md`

### Still needs a follow-up decision

- `_ai/requirements.md`
  - still empty and should either be filled or removed from the active workflow

---

## Structural Findings

### 1. Sync foundation exists, but order execution semantics are still incomplete

Current code has:

- provider boundary in `apps.integrations`
- local domain boundaries in `apps.orders` and `apps.listings`
- orchestration boundary in `apps.sync`

What is still missing is production-ready execution behavior for:

- backfill jobs
- incremental sync jobs
- replay of failed raw payloads
- provider-backed order parsing/upsert
- tests around retry / resume behavior

This keeps `apps.sync` justified, but the next slice should finish semantics, not add another boundary.

### 2. `integrations` should not become a dumping ground

`apps.integrations` should own:

- provider registry
- provider wrappers
- client construction from credentials
- provider capability metadata

It should not become the home of all high-level use cases.

### 3. Domain apps should stay local

- `apps.orders` should own the `Order` model, upsert behavior, and order lifecycle rules.
- `apps.listings` should own the `Listing` model, upsert behavior, and listing lifecycle rules.
- `apps.inventory` should own inventory state and inventory-specific rules.

### 4. The repo has hygiene noise

The workspace currently contains a large amount of runtime/build residue:

- many `__pycache__` directories
- `libs/apis_sdk/apis_sdk.egg-info`
- local `venv/`
- local `backend/db.sqlite3`

These are acceptable in a local workspace but should not be treated as project structure.

---

## Long-Term Target Architecture

### Boundary rules

- `apps.integrations`
  - talks to external providers
  - builds provider clients
  - returns normalized external data

- `apps.sync`
  - owns use cases and orchestration
  - owns checkpoints, run logs, resume logic, backfill logic
  - coordinates `integrations` with local domain apps

- `apps.orders`
  - owns local order persistence and invariants

- `apps.listings`
  - owns local listing persistence and invariants

- `apps.inventory`
  - owns local product persistence and invariants

### Current `apps.sync` shape

```text
backend/apps/sync/
  apps.py
  models.py
  admin.py
  management/
    commands/
      sync_orders.py
      sync_listings.py
  services/
    base.py
    orders.py
    listings.py
  dto/
    sync_result.py
```

### Initial sync models

- `SyncCheckpoint`
  - `integration_account`
  - `resource_type` (`orders`, `listings`)
  - `mode` (`backfill`, `incremental`)
  - `cursor`
  - `last_seen_remote_id`
  - `last_seen_remote_timestamp`
  - `last_run_at`
  - `status`
  - `meta`

- `SyncRun`
  - `resource_type`
  - `integration_account`
  - `mode`
  - `status`
  - `started_at`
  - `finished_at`
  - `processed_count`
  - `created_count`
  - `updated_count`
  - `error_count`
  - `meta`

---

## Immediate Decisions

These decisions should guide the next implementation work:

1. Internal domain name stays `listing`; provider-side `offer` remains an external alias only.
2. New cross-provider sync use cases go into `apps.sync`, not into `apps.orders` or `apps.integrations`.
3. Provider wrappers remain under `apps.integrations.providers`.
4. First execution mechanism should be Django management commands, not Celery.
5. Backfill and incremental sync must be separate modes from day one.
6. Resume state should be stored in DB checkpoints, not in files.

---

## Recommended Execution Order

### Phase 0 - Documentation cleanup

Status: completed

- refresh `README.md`
- refresh `_ai/architecture.md`
- add `docs/README.md`
- add `docs/ARCHITECTURE.md`
- add `docs/IMPLEMENTATION_PHASES.md`
- remove `django-migration-docs/`

### Phase 1 - Create the sync landing zone

Status: completed

- add `apps.sync`
- add `RawPayload`, `SyncCheckpoint`, and `SyncRun`
- register the app in settings and admin
- add `sync_orders` command skeleton

### Phase 2 - Order sync first

Status: in progress

- wire `sync_orders` to real provider fetch behavior
- add provider-to-domain order sync service
- support `backfill` and `incremental` modes end to end
- define replay behavior for failed raw payloads

### Phase 3 - Domain-safe order import

- create explicit order upsert service
- review signal side effects during backfill
- ensure historical imports do not corrupt current inventory state

### Phase 4 - Listing sync second

- add `sync_listings` command and service
- reuse checkpoint and run-log pattern

### Phase 5 - Tests before scheduler

- add unit tests for checkpoint logic
- add integration tests for provider page import and idempotent upsert
- only then evaluate Celery or another periodic runner

---

## What Not To Do Yet

- do not introduce Celery before order sync semantics are stable
- do not split the monolith into many new apps unless a real boundary exists
- do not move domain business rules into `apis_sdk`
- do not use `scripts/` for long-lived sync workflows

---

## Next Working Slice

The next implementation slice should be:

1. wire `OrderSyncService` to provider fetch + parse + upsert
2. add replay semantics for failed `RawPayload` rows
3. add tests for checkpoint, raw ingestion, and rerun safety

That is the cleanest continuation point for the project.
