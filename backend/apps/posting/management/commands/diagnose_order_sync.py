"""Read-only health report for order fetching + pool replenishment.

When "orders stop being fetched" and "keys stop being replenished" across
marketplaces, the cause is almost always visible in LOCAL sync state, without
touching any marketplace API:

  * A raw order payload that fails to apply locally (bad data, a missing game
    mapping, a decryption error, a parser bug) blocks the incremental
    checkpoint. If it keeps failing it is now *quarantined* after a few
    attempts (see ``BaseSyncService.MAX_PARSE_RETRY_ATTEMPTS``) so it no longer
    stalls the account — but the FAILED row is kept for manual review and shows
    up here (section C).
  * A failed / stalled order ``SyncRun`` (e.g. PA relay preflight raising, an
    auth error) means no new Orders were ingested, so ``notify_sale`` never
    fires and pools are neither marked sold nor replenished (sections A/B).
  * Pool offers stuck in ERROR / carrying a ``last_error`` never top up
    (section D) — this is what "not able to replenish keys for PA and GB"
    looks like from the DB.

Nothing is mutated. Use it to pinpoint WHY fetch/replenish stopped, then act
(re-run ``sync_orders``, warm the relay session, fix/clear the offending order,
run ``reconcile_pool_sale_bindings --apply``, etc.).

Examples::

    python manage.py diagnose_order_sync                       # all providers, 48h
    python manage.py diagnose_order_sync --hours 72
    python manage.py diagnose_order_sync --provider playerauctions
    python manage.py diagnose_order_sync --account playerauctions-csgosmurfkings
    python manage.py diagnose_order_sync --json /tmp/order_sync_health.json
"""
from __future__ import annotations

import json
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

ORDER_RESOURCES = ('orders', 'item_orders', 'historical_orders')


class Command(BaseCommand):
    help = "Report why order fetching / pool replenishment stopped (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=48)
        parser.add_argument(
            "--provider", default=None,
            help="Scope to one provider (e.g. playerauctions, gameboost, eldorado).",
        )
        parser.add_argument(
            "--account", default=None,
            help="Scope to one IntegrationAccount slug.",
        )
        parser.add_argument(
            "--json", default=None, dest="json_path",
            help="Optional path to write a machine-readable JSON report.",
        )

    def handle(self, *args, **options):
        from apps.integrations.models import IntegrationAccount
        from apps.posting.models import PoolOffer, PoolOfferStatus
        from apps.sync.enums import SyncRunStatus
        from apps.sync.models import RawPayload, SyncCheckpoint, SyncRun

        hours = max(1, options["hours"])
        since = timezone.now() - timedelta(hours=hours)
        provider = options["provider"]
        account_slug = options["account"]

        acct_filter: dict = {}
        if provider:
            acct_filter["provider"] = provider
        if account_slug:
            acct_filter["slug"] = account_slug

        accounts = list(
            IntegrationAccount.objects.filter(**acct_filter).order_by("provider", "slug")
        )
        report: dict = {
            "hours": hours, "provider": provider, "account": account_slug,
            "accounts": [], "failed_raw_payloads": [], "problem_offers": [],
        }

        # ── A. Latest order SyncRun per account/resource ──
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"A. Latest order sync run per account (last {hours}h window for 'stale')"
        ))
        problem_accounts = 0
        for acct in accounts:
            latest = (
                SyncRun.objects.filter(
                    integration_account=acct,
                    resource_type__in=ORDER_RESOURCES,
                )
                .order_by("-started_at")
                .first()
            )
            if latest is None:
                continue
            blocked = bool(latest.meta.get("checkpoint_blocked_on_parse_failure"))
            quarantined = latest.meta.get("quarantined_remote_ids") or []
            stop_reason = latest.meta.get("stop_reason")
            stale = latest.started_at < since
            is_problem = (
                latest.status == SyncRunStatus.FAILED
                or latest.error_count > 0
                or blocked or bool(quarantined) or stale
            )
            if is_problem:
                problem_accounts += 1
            marker = "PROBLEM" if is_problem else "ok"
            self.stdout.write(
                f"  [{marker}] {acct.provider}/{acct.slug}: run {latest.pk} "
                f"status={latest.status} started={latest.started_at:%Y-%m-%d %H:%M} "
                f"processed={latest.processed_count} created={latest.created_count} "
                f"errors={latest.error_count}"
            )
            if blocked:
                self.stdout.write("       -> checkpoint BLOCKED on a parse failure")
            if quarantined:
                self.stdout.write(f"       -> quarantined remote_ids: {quarantined}")
            if stop_reason:
                self.stdout.write(f"       -> stop_reason: {stop_reason}")
            report["accounts"].append({
                "provider": acct.provider, "slug": acct.slug,
                "run_id": latest.pk, "status": latest.status,
                "started_at": latest.started_at, "error_count": latest.error_count,
                "checkpoint_blocked": blocked, "quarantined": quarantined,
                "stop_reason": stop_reason, "stale": stale, "problem": is_problem,
            })
        if not report["accounts"]:
            self.stdout.write("  (no order sync runs found for the selected scope)")

        # ── B. Stalled/blocked order checkpoints ──
        cps = SyncCheckpoint.objects.filter(
            resource_type__in=ORDER_RESOURCES,
            integration_account__in=accounts,
        ).select_related("integration_account")
        stalled_cps = [
            cp for cp in cps
            if cp.last_run_at is None or cp.last_run_at < since
            or cp.meta.get("checkpoint_blocked_on_parse_failure")
        ]
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"B. Order checkpoints not advanced in {hours}h / blocked: {len(stalled_cps)}"
        ))
        for cp in stalled_cps:
            acct = cp.integration_account
            last_run = (
                f"{cp.last_run_at:%Y-%m-%d %H:%M}" if cp.last_run_at else "never"
            )
            self.stdout.write(
                f"  {acct.provider}/{acct.slug} [{cp.mode}] last_seen_remote_id="
                f"{cp.last_seen_remote_id or '—'} last_run={last_run}"
            )

        # ── C. FAILED raw order payloads (the poison pills) ──
        failed = (
            RawPayload.objects.filter(
                resource_type__in=ORDER_RESOURCES,
                parse_status="failed",
                integration_account__in=accounts,
            )
            .select_related("integration_account")
            .order_by("-fetched_at")[:100]
        )
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"C. FAILED raw order payloads (block/quarantine the checkpoint): {len(failed)}"
        ))
        for raw in failed:
            acct = raw.integration_account
            attempts = raw.meta.get("parse_attempts", "?")
            self.stdout.write(
                f"  {acct.provider}/{acct.slug} order {raw.remote_id} "
                f"attempts={attempts} fetched={raw.fetched_at:%Y-%m-%d %H:%M}"
            )
            if raw.parse_error:
                self.stdout.write(f"      error: {raw.parse_error[:200]}")
            report["failed_raw_payloads"].append({
                "provider": acct.provider, "slug": acct.slug,
                "remote_id": raw.remote_id, "parse_attempts": attempts,
                "parse_error": (raw.parse_error or "")[:300],
            })

        # ── D. Pool offers stuck in ERROR / carrying last_error (no replenish) ──
        offers = (
            PoolOffer.objects.filter(
                listing__integration_account__in=accounts,
            )
            .select_related("listing", "listing__integration_account", "pool", "pool__game")
        )
        problem_offers = [
            po for po in offers
            if po.status == PoolOfferStatus.ERROR or po.last_error
            or (po.current_remote_count is not None and po.current_remote_count <= po.threshold)
        ]
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"D. Pool offers in ERROR / with last_error / below threshold: "
            f"{len(problem_offers)}"
        ))
        for po in problem_offers:
            acct = po.listing.integration_account if po.listing else None
            prov = acct.provider if acct else "—"
            game = getattr(getattr(po.pool, "game", None), "slug", "—")
            self.stdout.write(
                f"  pool_offer {po.pk} {prov} game={game} status={po.status} "
                f"remote={po.current_remote_count} thr={po.threshold}"
            )
            if po.last_error:
                self.stdout.write(f"      last_error: {po.last_error[:200]}")
            report["problem_offers"].append({
                "pool_offer_id": po.pk, "provider": prov, "game": game,
                "status": po.status, "remote": po.current_remote_count,
                "threshold": po.threshold, "last_error": (po.last_error or "")[:300],
            })

        # ── Summary ──
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"SUMMARY (last {hours}h): problem_accounts={problem_accounts} | "
            f"stalled_checkpoints={len(stalled_cps)} | failed_order_payloads={len(failed)} | "
            f"problem_offers={len(problem_offers)}"
        ))
        self.stdout.write(
            "Interpretation:\n"
            "  * Section C non-empty -> specific orders can't be applied locally and "
            "were blocking (now bounded/quarantined) the checkpoint. Read the error, "
            "fix the root cause (mapping/data), then those orders re-apply.\n"
            "  * Section A/B FAILED or stale -> order fetch itself is erroring "
            "(e.g. PA relay preflight). Restore the relay/session, then re-run "
            "`sync_orders <account> --mode incremental`.\n"
            "  * Section D -> offers that won't top up. After orders flow again, run "
            "`reconcile_pool_sale_bindings --apply` and trigger a pool replenish."
        )

        if options["json_path"]:
            with open(options["json_path"], "w", encoding="utf-8") as fh:
                json.dump(report, fh, indent=2, default=str)
            self.stdout.write(f"JSON written to {options['json_path']}")
