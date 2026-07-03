# Docs Index

Last updated: 2026-03-28

## Purpose

This folder contains the living project documentation.

If a document under `docs/` conflicts with an older note elsewhere in the
repository, `docs/` wins.

## Active documents

- `ARCHITECTURE.md`
  - current app boundaries
  - ownership rules
  - target direction for `apps.sync`
- `IMPLEMENTATION_PHASES.md`
  - phase-by-phase execution plan
  - current phase status
- `PROJECT_AUDIT_AND_ROADMAP.md`
  - repo audit
  - documentation hygiene decisions
  - long-term roadmap context
- `SYNC_RAW_PIPELINE_DESIGN_NOTE.md`
  - target design for order/listing sync staging
  - `RawPayload` semantics
  - ingest vs parse/reprocess split
- `r6-tracker-server-setup.md`
  - R6 (Rainbow Six) tracker server requirements (Xvfb + real Chrome)
  - Cloudflare / cf_clearance setup + the datacenter-IP blocker
  - what to install on a new server so the R6 sheet flow works
- `deploy-runbook.md`
  - service map (xvfb + ecom-* + nginx) and one-script deploy
  - step-by-step manual diagnosis when something fails
  - legacy AdsPower/PA-token removal note

## Related sources

- `_ai/spec.md`
  - product scope and high-level goals
- `_ai/decisions.md`
  - ADR log
- `_ai/todo.md`
  - active and upcoming work items
- `_data_samples/`
  - provider sample payloads used during integration work
- `_helpers_folders/old_system_refferances/INVENTORY_MODELS_EXPORT.md`
  - old system schema reference only

## Rule

Do not add new architecture or implementation-plan documents outside `docs/`
unless there is a strong reason.
