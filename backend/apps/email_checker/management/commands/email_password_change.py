"""Bulk email password changer — Django management command.

Usage::

    python manage.py email_password_change \\
        --provider firstmail \\
        [--category steam] \\
        [--limit 10] \\
        [--delay 0.2] \\
        [--new-password "MyCustomPass123!"] \\
        [--dry-run] \\
        [--output-dir output/password_changer]

ServiceCredential records with service_type='firstmail' and matching provider
are loaded automatically. Multiple credentials are used in round-robin
(pool) mode — if one hits rate limit, next credential is used.
"""
from __future__ import annotations

import csv
import itertools
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apis_sdk.clients.services.firstmail.client import FirstMailClient
from apis_sdk.clients.services.firstmail.config import FirstMailConfig
from apis_sdk.clients.services.firstmail.facade import FirstMailFacade
from apis_sdk.factories.transport_factory import TransportFactory

from apps.email_checker.services.input_parser import mask_email, mask_password
from apps.email_checker.services.password_changer.changer import EmailPasswordChanger
from apps.email_checker.services.password_changer.finder import find_firstmail_owned_products
from apps.email_checker.services.password_changer.types import ChangeStatus, PasswordChangeResult
from apps.integrations.models import ServiceCredential

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://firstmail.ltd/api/v1"


class Command(BaseCommand):
    help = (
        "Change email passwords for OwnedProduct records via FirstMail API. "
        "Multiple ServiceCredential records are used in round-robin pool."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--provider", default="firstmail",
            help="Email provider (default: firstmail)",
        )
        parser.add_argument(
            "--category", default=None,
            help="Category slug filter (e.g. steam, supercell)",
        )
        parser.add_argument(
            "--limit", type=int, default=0,
            help="Max accounts to process (0 = all)",
        )
        parser.add_argument(
            "--delay", type=float, default=0.2,
            help="Seconds between API calls (default: 0.2)",
        )
        parser.add_argument(
            "--new-password", default=None,
            help="Fixed new password (omit for auto-generated random)",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show target list without calling API",
        )
        parser.add_argument(
            "--output-dir", default="",
            help="Output directory for JSON + CSV results",
        )

    def handle(self, *args, **opts):
        provider = opts["provider"]
        if provider != "firstmail":
            raise CommandError(f"Unsupported provider: {provider}. Only 'firstmail' is supported.")

        # Load all active FirstMail credentials → pool
        facades = self._build_facade_pool()
        if not facades:
            raise CommandError(
                "No active ServiceCredential with service_type='firstmail' found. "
                "Create one in Django Admin → Service Credentials."
            )
        self.stdout.write(f"Loaded {len(facades)} FirstMail credential(s) for pool")

        # Find target OwnedProducts
        category_id = self._resolve_category(opts["category"]) if opts["category"] else None
        qs = find_firstmail_owned_products(category_id=category_id)

        limit = max(0, opts["limit"])
        if limit:
            qs = qs[:limit]

        targets = list(qs)
        if not targets:
            self.stdout.write(self.style.WARNING("No matching OwnedProduct records found."))
            return

        self.stdout.write(f"Found {len(targets)} target account(s)")

        # Dry run — just show targets
        if opts["dry_run"]:
            self.stdout.write(self.style.NOTICE("=== DRY RUN — no API calls ==="))
            for op in targets:
                self.stdout.write(
                    f"  [{op.id}] {mask_email(op.email)} | "
                    f"pass={mask_password(op.email_password)} | "
                    f"category={op.category}"
                )
            self.stdout.write(f"Total: {len(targets)} accounts would be processed.")
            return

        # Process — round-robin across facades
        delay = max(0.0, opts["delay"])
        new_password = opts["new_password"]
        facade_cycle = itertools.cycle(facades)

        results: list[PasswordChangeResult] = []
        for i, op in enumerate(targets):
            if i > 0 and delay > 0:
                time.sleep(delay)

            facade = next(facade_cycle)
            changer = EmailPasswordChanger(facade)

            result = changer.change_and_persist(op, new_password=new_password)
            results.append(result)
            self._log_result(result)

            # On rate limit, try next credential immediately (skip delay)
            if result.status == ChangeStatus.RATE_LIMITED and len(facades) > 1:
                self.stdout.write(self.style.WARNING(
                    "  → Rate limited, rotating to next credential..."
                ))

        # Write output
        self._write_output(results, opts["output_dir"])
        self._write_summary(results)

    # -----------------------------------------------------------------
    # Facade pool builder
    # -----------------------------------------------------------------

    def _build_facade_pool(self) -> list[FirstMailFacade]:
        """Load all active email ServiceCredentials and build FirstMailFacade instances."""
        creds = ServiceCredential.objects.filter(
            service_type="firstmail",
            is_active=True,
        ).order_by("id")

        facades: list[FirstMailFacade] = []
        for sc in creds:
            api_key = sc.credentials.get("api_key", "")
            if not api_key:
                self.stdout.write(self.style.WARNING(
                    f"  Skipping '{sc.name}' — no api_key in credentials"
                ))
                continue

            base_url = sc.credentials.get("base_url") or sc.base_url or DEFAULT_BASE_URL
            # Strip trailing slash from base_url for clean URL building
            base_url = base_url.rstrip("/")

            config = FirstMailConfig(api_key=api_key, base_url=base_url)
            transport = TransportFactory.create_requests_transport(timeout=30.0)
            client = FirstMailClient(config, transport)
            facade = FirstMailFacade(client, config=config)
            facades.append(facade)
            self.stdout.write(f"  Credential: {sc.name} ({sc.slug})")

        return facades

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _resolve_category(slug: str) -> int:
        from apps.inventory.models import Category
        try:
            return Category.objects.get(slug=slug).id
        except Category.DoesNotExist as exc:
            raise CommandError(f'Category "{slug}" not found.') from exc

    def _log_result(self, r: PasswordChangeResult) -> None:
        icons = {
            "success": "OK  ",
            "wrong_password": "WPWD",
            "not_found": "NFND",
            "validation_error": "VALD",
            "rate_limited": "RATE",
            "forbidden": "FORB",
            "server_error": "SERR",
            "network_error": "NTWK",
            "unknown": "?   ",
        }
        icon = icons.get(r.status.value, "?   ")
        db_tag = " [DB updated]" if r.db_updated else ""
        self.stdout.write(
            f"{icon} {mask_email(r.email):40s} {r.detail}{db_tag} ({r.elapsed_ms}ms)"
        )

    def _write_output(self, results: list[PasswordChangeResult], output_dir: str) -> None:
        if output_dir:
            out = Path(output_dir)
        else:
            from django.conf import settings
            out = settings.ROOT_DIR / "output" / "password_changer"

        out.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # JSON
        json_path = out / f"password_change_{ts}.json"
        data = {
            "generated_at": datetime.now().isoformat(),
            "count": len(results),
            "results": [r.to_dict() for r in results],
        }
        json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        # CSV
        csv_path = out / f"password_change_{ts}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow([
                "email", "status", "provider", "new_password",
                "detail", "elapsed_ms", "owned_product_id", "db_updated",
            ])
            for r in results:
                writer.writerow([
                    r.email, r.status.value, r.provider.value, r.new_password,
                    r.detail, r.elapsed_ms, r.owned_product_id, r.db_updated,
                ])

        self.stdout.write(f"JSON: {json_path}")
        self.stdout.write(f"CSV : {csv_path}")

    def _write_summary(self, results: list[PasswordChangeResult]) -> None:
        success = sum(1 for r in results if r.success)
        failed = len(results) - success
        db_updated = sum(1 for r in results if r.db_updated)

        by_status: dict[str, int] = {}
        for r in results:
            by_status[r.status.value] = by_status.get(r.status.value, 0) + 1

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {success} success, {failed} failed, {db_updated} DB updated."
        ))
        for status, count in sorted(by_status.items()):
            self.stdout.write(f"  {status}: {count}")
