# Architecture

Last updated: 2026-03-22

## Purpose

This document describes the current architecture of the project and the next
planned boundary changes. It is based on the existing codebase, not on older
migration-era plans.

## Current project style

- Pattern: Django modular monolith
- Main UI: Django templates
- Main persistence: Django ORM
- External access: provider wrappers under `apps.integrations.providers`
- Background model: management commands first, scheduler later

## Current app boundaries

### `apps.accounts`

- user model
- auth views
- permissions

### `apps.inventory`

- `Category`
- `Game`
- `OwnedProduct`
- `DropshipProduct`
- inventory-local rules and helpers

### `apps.integrations`

- `IntegrationAccount`
- `IntegrationCredential`
- provider registry
- provider wrappers
- client construction from DB-backed credentials

This app owns external provider access. It should not become the home of every
high-level workflow.

### `apps.listings`

- local `Listing` state
- `ListingOwnedProduct`
- listing lifecycle rules

Internal canonical term is `listing`.
Provider-side names like `offer` stay external aliases only.

### `apps.orders`

- local `Order` state
- order lifecycle rules
- local order-side invariants

### `apps.dashboard`

- template-based dashboard views

## `apps.sync`

### Why it exists

`apps.sync` owns use-case orchestration that is shared by multiple
resources, such as:

- order sync
- listing sync
- future stock or message sync

### What belongs in `apps.sync`

- raw payload ingestion (`RawPayload`)
- sync checkpoints (`SyncCheckpoint`)
- sync run logs (`SyncRun`)
- backfill vs incremental execution modes
- orchestration services
- management commands

### What does not belong in `apps.sync`

- provider HTTP details
- raw client construction
- domain-specific order or listing invariants

## Ownership rules

### `apps.integrations`

Owns:

- provider-specific credential schema
- client construction
- provider wrapper methods like `fetch_orders()` and `fetch_products()`
- provider capability knowledge

Does not own:

- checkpoint state
- long-running sync orchestration
- order/listing local business rules

### `apps.sync`

Owns:

- orchestration and resume logic
- sync checkpoints
- sync run history
- management-command entrypoints

Does not own:

- provider credentials
- local order/listing model rules

### `apps.orders`

Owns:

- local order persistence
- idempotent order upsert behavior
- order lifecycle effects

### `apps.listings`

Owns:

- local listing persistence
- idempotent listing upsert behavior
- listing lifecycle effects

### `apps.inventory`

Owns:

- local product state
- local stock and ownership rules

## Current execution approach

The first sync implementation should use Django management commands.

Reason:

- less moving infrastructure
- easier debugging
- easier checkpoint validation
- no scheduler complexity before sync semantics stabilize

Celery can be added later if the sync semantics and tests become stable.

## Data and naming rules

- Internal name: `listing`
- External alias: `offer`
- Account config model: `IntegrationAccount`
- Credential model: `IntegrationCredential`
- Resume state must live in DB, not in JSON files
- Backfill and incremental sync must be separate modes

## Current shape of `apps.sync`

```text
backend/apps/sync/
  apps.py
  enums.py
  models.py          # RawPayload, SyncCheckpoint, SyncRun
  admin.py
  management/
    commands/
      sync_orders.py
  services/
    base.py           # BaseSyncService (fetch → ingest → parse loop)
    orders.py          # OrderSyncService (skeleton)
```

## Sync models

### `RawPayload`

Stores raw provider JSON before parsing. Latest-snapshot with upsert
keyed on `(integration_account, resource_type, remote_id)`.

Key fields: `payload`, `payload_hash`, `parse_status`, `first_seen_at`,
`last_seen_at`, `fetched_at`, `parsed_at`, `parse_error`, `meta`.

### `SyncCheckpoint`

Cursor/resume state for a sync stream. One row per
`(integration_account, resource_type, mode)`.

Key fields: `cursor`, `last_seen_remote_id`, `last_seen_remote_timestamp`,
`last_run_at`, `status`, `meta`.

### `SyncRun`

Audit log for each sync execution.

Key fields: `status`, `started_at`, `finished_at`, `processed_count`,
`created_count`, `updated_count`, `error_count`, `meta`.

## Constraints for the next implementation

- keep provider access in `apps.integrations.providers`
- keep local domain rules in `apps.orders`, `apps.listings`, and `apps.inventory`
- do not use `scripts/` for long-lived sync workflows
- do not add Celery before order-sync semantics are stable
