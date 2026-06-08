"""Backfill new Eldorado offer attributes onto already-listed accounts.

Existing Eldorado listings were created before extra game attributes (e.g.
Fortnite emotes / outfits / pickaxes / vbucks) were added to the payload
pipeline builders.  This command re-resolves each listing from its stored
source data (OwnedProduct / DropshipProduct ``raw_data``) through the SAME
payload pipeline used at posting time, then pushes the freshly-built
``augmentedGame`` block (which now carries the new ``offerAttributes``) to
Eldorado.

Strategy (chosen with the team):
    * ``relist`` (default) — delete + recreate, preserving the listing's price,
      title, images and credentials (taken from the live offer) and swapping in
      the rebuilt ``augmentedGame`` block with the new attributes.  This is the
      ONLY way to change attributes: Eldorado offers are immutable after
      creation — the offer endpoint rejects PUT/PATCH/POST with HTTP 405.
      Recreating gives the offer a new id and resets its age / expiry timer.
    * ``put``    — diagnostic only.  Sends a partial update via the offer PUT
      endpoint; Eldorado returns 405, so this never succeeds.  Kept so the
      405 behaviour can be re-confirmed if the API changes.
    * ``auto``   — alias for ``relist`` (PUT is known-dead, so no point trying).

Default is a DRY RUN (no marketplace writes): it prints the old vs new
attribute diff so you can eyeball the rebuild before applying.

Examples:
    # Canary — inspect one listing, no writes
    python manage.py backfill_eldorado_attributes --game fortnite --listing-id 29741

    # Canary — actually PUT one listing
    python manage.py backfill_eldorado_attributes --game fortnite \\
        --listing-id 29741 --apply --mode put

    # Dry-run across all LISTED instant fortnite listings
    python manage.py backfill_eldorado_attributes --game fortnite --kind instant
"""

from __future__ import annotations

import json
import time

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from apps.integrations.providers import registry
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name
from apps.listings.enums import ListingStatus
from apps.listings.models import Listing
from apps.posting.pipeline import adapter
from apps.posting.services.shared.pricing import STOCK_PRICING_BASELINE
from apps.posting.services.variant_context import build_variant_context
from payload_pipeline.core.contracts import ListingKind

_STATUS_MAP = {
    "LISTED": ListingStatus.LISTED,
    "PAUSED": ListingStatus.PAUSED,
    "DELETED": ListingStatus.DELETED,
}


class Command(BaseCommand):
    help = "Re-push freshly-built attributes onto existing Eldorado listings."

    def add_arguments(self, parser):
        parser.add_argument("--game", default="fortnite", help="Game slug (default: fortnite).")
        parser.add_argument("--listing-id", type=int, default=None, help="Target a single listing id.")
        parser.add_argument("--limit", type=int, default=None, help="Cap the number of listings processed.")
        parser.add_argument(
            "--status", default="LISTED", choices=sorted(_STATUS_MAP),
            help="Listing status filter (default: LISTED).",
        )
        parser.add_argument(
            "--kind", default="instant", choices=["instant", "dropship", "all"],
            help="Which listing kinds to process (default: instant).",
        )
        parser.add_argument(
            "--mode", default="relist", choices=["put", "relist", "auto"],
            help="Push strategy when --apply is set (default: relist; auto==relist).",
        )
        parser.add_argument(
            "--apply", action="store_true",
            help="Actually push to Eldorado. Without this flag the command is a dry run.",
        )
        parser.add_argument(
            "--sleep", type=float, default=0.0,
            help="Seconds to wait between listings (rate-limit throttle). Use e.g. 30 with --apply.",
        )

    # ── selection ────────────────────────────────────────────────

    def handle(self, *args, **opts):
        qs = (
            Listing.objects
            .filter(integration_account__provider="eldorado", game__slug=opts["game"])
            .filter(status=_STATUS_MAP[opts["status"]])
            .select_related("integration_account", "game", "dropship_product")
        )
        if opts["kind"] == "instant":
            qs = qs.filter(is_instant=True)
        elif opts["kind"] == "dropship":
            qs = qs.filter(is_instant=False)

        if opts["listing_id"] is not None:
            # Explicit target: don't pre-filter by source so any listing can be
            # inspected. _process() still guards non-rebuildable sources.
            qs = qs.filter(id=opts["listing_id"])
        elif opts["kind"] == "instant":
            # Restrict the batch to rebuildable instant sources (LZT / manual).
            # Cross-source listings (gameboost / eldorado / playerauctions) can't
            # be rebuilt from stored data, so exclude them up front — otherwise
            # --limit gets consumed by skips. Allowlist form: any unknown source
            # is excluded by default.
            rebuildable = (
                Q(listing_owned_products__owned_product__raw_data__source="manual")
                | Q(listing_owned_products__owned_product__source_account__provider="lzt")
                | Q(listing_owned_products__owned_product__source_account__isnull=True)
            )
            qs = qs.filter(rebuildable).distinct()

        qs = qs.order_by("id")
        if opts["limit"]:
            qs = qs[: opts["limit"]]

        listings = list(qs)
        if not listings:
            raise CommandError("No matching listings found.")

        dry = not opts["apply"]
        self.stdout.write(
            f"{'DRY RUN' if dry else 'APPLY (' + opts['mode'] + ')'}: "
            f"{len(listings)} {opts['game']} listing(s), status={opts['status']}, kind={opts['kind']}"
        )

        sleep_s = opts["sleep"]
        last = len(listings) - 1
        ok = fail = skip = 0
        for idx, lst in enumerate(listings):
            try:
                result = self._process(lst, dry=dry, mode=opts["mode"])
            except Exception as exc:  # noqa: BLE001 — report and continue the batch
                self.stderr.write(self.style.ERROR(f"#{lst.id}: EXCEPTION {exc}"))
                fail += 1
                result = "fail"
            else:
                if result == "ok":
                    ok += 1
                elif result in ("skip", "uptodate"):
                    skip += 1
                else:
                    fail += 1
            # Throttle between listings to stay under Eldorado's rate limit — but
            # only when we actually hit the marketplace. Already-up-to-date
            # listings short-circuit before any Eldorado call, so don't waste the
            # sleep on them.
            if sleep_s and idx < last and result != "uptodate":
                time.sleep(sleep_s)

        self.stdout.write(self.style.SUCCESS(f"Done. ok={ok} fail={fail} skip={skip}"))

    # ── per-listing ──────────────────────────────────────────────

    def _process(self, lst: Listing, *, dry: bool, mode: str) -> str:
        raw, source_key, kind = self._source(lst)
        if raw is None:
            return "skip"
        if source_key not in ("lzt", "manual"):
            self.stderr.write(self.style.WARNING(
                f"#{lst.id}: source '{source_key}' cannot be rebuilt from stored data — skip"
            ))
            return "skip"

        payload = self._rebuild(lst, raw, source_key, kind)
        if payload is None:
            return "fail"

        new_ag = payload.get("augmentedGame", {})
        new_attrs = new_ag.get("offerAttributes") or []
        old_attrs = self._current_attrs(lst)

        # Idempotency: if the offer already carries exactly these attributes,
        # there's nothing to do. Skip BEFORE probing/relisting so re-runs don't
        # needlessly recreate (and reset the age of) already-updated offers.
        if new_attrs and self._norm(old_attrs) == self._norm(new_attrs):
            self.stdout.write(
                f"#{lst.id} offer={lst.store_listing_id}: attributes already up to date — skip"
            )
            # No marketplace call was made — signal the caller to skip the throttle.
            return "uptodate"

        # Ghost guard: probe the marketplace BEFORE we ever delete+recreate.
        # An offer that is LISTED in our DB may already be gone on Eldorado;
        # relisting it would resurrect a ghost the seller intentionally removed.
        exists = self._offer_exists(lst)
        remote = {True: "yes", False: "GONE(404)", None: "unknown"}[exists]

        self.stdout.write(
            f"#{lst.id} offer={lst.store_listing_id} variant={lst.variant} remote={remote}\n"
            f"  OLD: {self._fmt(old_attrs)}\n"
            f"  NEW: {self._fmt(new_attrs)}"
        )

        if not new_attrs:
            self.stderr.write(self.style.WARNING(f"#{lst.id}: rebuild produced no attributes — skip"))
            return "skip"

        # Definitively gone on remote → never recreate. Self-heal the DB instead.
        if exists is False:
            if not dry:
                self._mark_listing_deleted(lst)
                self.stdout.write(self.style.WARNING(
                    f"#{lst.id}: remote offer gone (404) — marked DELETED, not relisted"
                ))
            return "skip"

        # Existence could not be verified (timeout / proxy / 5xx) → touch nothing.
        if exists is None:
            self.stderr.write(self.style.WARNING(
                f"#{lst.id}: remote existence unverified — skip (no action taken)"
            ))
            return "skip"

        if dry:
            return "ok"

        if mode == "put":
            return self._put(lst, new_ag)
        return self._relist(lst, new_ag)

    def _source(self, lst: Listing):
        """Return (raw_data, source_key, ListingKind) for *lst*, or (None, ..) if missing."""
        if lst.is_instant:
            lop = lst.listing_owned_products.select_related("owned_product__source_account").first()
            op = lop.owned_product if lop else None
            raw = getattr(op, "raw_data", None)
            if not raw:
                self.stderr.write(self.style.WARNING(f"#{lst.id}: no source raw_data — skip"))
                return None, None, None
            if isinstance(raw, dict) and raw.get("source") == "manual":
                key = "manual"
            elif op.source_account and op.source_account.provider:
                key = op.source_account.provider
            else:
                key = "lzt"
            return raw, key, ListingKind.STOCK

        dp = lst.dropship_product
        raw = getattr(dp, "raw_data", None)
        if not raw:
            self.stderr.write(self.style.WARNING(f"#{lst.id}: no source raw_data — skip"))
            return None, None, None
        key = (dp.source_account.provider if dp.source_account else None) or "lzt"
        return raw, key, ListingKind.DROPSHIPPING

    def _rebuild(self, lst: Listing, raw: dict, source_key: str, kind) -> dict | None:
        """Re-run the payload pipeline; returns the freshly built Eldorado payload."""
        pr = adapter.prepare(game_slug=lst.game.slug, sources={source_key: raw}, kind=kind, disable_media=True)
        if not pr.success:
            self.stderr.write(self.style.ERROR(f"#{lst.id}: prepare failed: {pr.error}"))
            return None

        vctx = build_variant_context(store=lst.integration_account, game=lst.game, marketplace="eldorado")
        br = adapter.build(
            prepared=pr.prepared,
            marketplace="eldorado",
            pricing_defaults=STOCK_PRICING_BASELINE,
            store=lst.integration_account,
            game=lst.game,
            kind=kind,
            variant_slug=lst.variant or "",
            variant_context=vctx,
        )
        if not br.success:
            self.stderr.write(self.style.ERROR(f"#{lst.id}: build failed: {br.error}"))
            return None
        return br.payload

    def _relist(self, lst: Listing, new_ag: dict) -> str:
        """Delete + recreate, swapping in the rebuilt augmentedGame (new attributes)."""
        from apps.posting.services.relist import relist_listing

        result = relist_listing(lst, augmented_game_override=new_ag)
        if result.ok:
            new = result.new_listing
            self.stdout.write(self.style.SUCCESS(
                f"#{lst.id}: relisted → #{new.id} offer={new.store_listing_id}"
            ))
            return "ok"
        self.stderr.write(self.style.ERROR(f"#{lst.id}: relist failed: {result.error}"))
        return "fail"

    def _put(self, lst: Listing, new_ag: dict) -> str:
        """Send a partial update with only the rebuilt augmentedGame block."""
        store = lst.integration_account
        proxy_pool = build_proxy_pool()
        proxy_group = get_group_name(store)
        client = registry.get_or_build_client(
            "eldorado", store.credential, proxy_pool=proxy_pool, proxy_group=proxy_group,
        )
        update_payload = {"augmentedGame": new_ag}
        result = client.update_offer(lst.store_listing_id, update_payload, proxy_group=proxy_group)
        if getattr(result, "ok", False):
            self.stdout.write(self.style.SUCCESS(f"#{lst.id}: PUT ok"))
            return "ok"
        self.stderr.write(self.style.ERROR(f"#{lst.id}: PUT failed: {getattr(result, 'error', result)}"))
        return "fail"

    # ── ghost guard ──────────────────────────────────────────────

    def _offer_exists(self, lst: Listing) -> bool | None:
        """Probe Eldorado for the offer.

        Returns:
            True  — offer is live on remote (safe to relist).
            False — offer is definitively gone (HTTP 404); do NOT recreate.
            None  — existence could not be verified (timeout / proxy / 5xx);
                    caller must take no action to avoid touching a real offer.
        """
        store = lst.integration_account
        proxy_pool = build_proxy_pool()
        proxy_group = get_group_name(store)
        provider = registry.get_provider("eldorado")
        client = registry.get_or_build_client(
            "eldorado", store.credential, proxy_pool=proxy_pool, proxy_group=proxy_group,
        )
        try:
            result = provider.fetch_offer_account_details(client, lst.store_listing_id)
        except Exception as exc:  # noqa: BLE001 — unknown failure → treat as unverified
            self.stderr.write(self.style.WARNING(f"#{lst.id}: existence probe error ({exc}) — unknown"))
            return None

        if getattr(result, "ok", False):
            return True
        code = getattr(result, "status_code", None)
        if code is None and getattr(result, "error", None) is not None:
            code = getattr(result.error, "status_code", None)
        if code == 404:
            return False
        return None

    @staticmethod
    def _mark_listing_deleted(lst: Listing) -> None:
        """Flip a DB listing to DELETED (self-heal when remote offer is gone)."""
        lst.status = ListingStatus.DELETED
        lst.removed_at = timezone.now()
        lst.save(update_fields=["status", "removed_at", "updated_at"])

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _current_attrs(lst: Listing) -> list:
        """Attributes already on record, from either storage shape:

        - legacy create envelope: raw_data['payload']['augmentedGame']['offerAttributes']
        - flat sync/relist format: raw_data['attributes'] (value is a nested dict)
        """
        raw = lst.raw_data or {}
        if not isinstance(raw, dict):
            return []
        payload = raw.get("payload")
        if isinstance(payload, dict):
            ag = payload.get("augmentedGame", {})
            if ag.get("offerAttributes"):
                return ag["offerAttributes"]
        flat = raw.get("attributes")
        if isinstance(flat, list) and flat:
            return flat
        return []

    @staticmethod
    def _norm(attrs: list) -> dict:
        """Normalize an attribute list (either shape) to {id: value_id} for comparison."""
        out: dict = {}
        for a in attrs or []:
            if not isinstance(a, dict) or a.get("id") is None:
                continue
            v = a.get("value")
            if isinstance(v, dict):
                v = v.get("id")
            out[a["id"]] = v
        return out

    @classmethod
    def _fmt(cls, attrs: list) -> str:
        if not attrs:
            return "(none on record)"
        return ", ".join(f"{k}={v}" for k, v in cls._norm(attrs).items())
