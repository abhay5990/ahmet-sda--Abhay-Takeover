# Implementation Phases

Last updated: 2026-03-22

## Purpose

This document is the active execution plan for the next architectural work.

## Status legend

- `completed`
- `in_progress`
- `pending`

## Phase 1 - Documentation cleanup

Status: `completed`

Goals:

- remove stale migration-era documents
- create a single living docs area under `docs/`
- align `README.md` and `_ai/architecture.md` with the current codebase

Deliverables:

- `docs/README.md`
- `docs/ARCHITECTURE.md`
- `docs/IMPLEMENTATION_PHASES.md`
- updated `README.md`
- updated `_ai/architecture.md`
- legacy `django-migration-docs/` removed

## Phase 2 - Sync foundation

Status: `completed`

Goals:

- add `apps.sync`
- create shared sync persistence primitives
- establish the orchestration boundary cleanly

Deliverables:

- `backend/apps/sync/apps.py`
- `backend/apps/sync/enums.py`
- `backend/apps/sync/models.py` — `RawPayload`, `SyncCheckpoint`, `SyncRun`
- `backend/apps/sync/admin.py`
- `backend/apps/sync/services/base.py` — `BaseSyncService`
- `backend/apps/sync/services/orders.py` — `OrderSyncService` (skeleton)
- `backend/apps/sync/management/commands/sync_orders.py`
- app registration in settings
- initial migration `0001_initial`

Acceptance:

- project boots with `apps.sync` — verified via `manage.py check`
- admin shows sync models
- checkpoint, run-log, and raw payload primitives exist
- management command skeleton validates account and credentials

## Phase 3 - Order sync first

Status: `pending`

Goals:

- implement historical backfill
- implement incremental resume behavior
- make order imports idempotent

Deliverables:

- `sync_orders` management command
- order sync orchestration service
- checkpoint update rules
- order upsert boundary review

Acceptance:

- a backfill run can continue from the last checkpoint
- rerunning the same batch does not create duplicate orders
- the sync can be executed account by account

## Phase 4 - Listing sync second

Status: `pending`

Goals:

- reuse the same checkpoint pattern for listings
- normalize provider-side offers into local listings

Deliverables:

- `sync_listings` management command
- listing sync orchestration service
- listing checkpoint handling

Acceptance:

- listing sync uses the same orchestration shape as order sync
- provider-side offer naming does not leak into the local domain model

## Phase 5 - Test coverage for sync boundaries

Status: `pending`

Goals:

- cover the new sync primitives before adding scheduling complexity

Deliverables:

- unit tests for checkpoint logic
- integration tests for provider-page ingestion
- integration tests for idempotent upserts

Acceptance:

- sync state transitions are test-covered
- rerun safety is verified by tests

## Phase 6 - Scheduler and automation

Status: `pending`

Goals:

- decide whether a scheduler is needed after sync semantics are stable

Options:

- Django management commands triggered externally
- Celery beat + workers
- another lightweight scheduler

Rule:

Do not start this phase before Phases 2 to 5 are stable.
