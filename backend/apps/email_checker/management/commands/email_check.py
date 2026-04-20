"""Email:password bulk verifier — Django management command.

Usage::

    python manage.py email_check \\
        --input emails.txt \\
        --lzt-account lzt-gandalfrivendell \\
        [--fetch-emails 20] \\
        [--scan-keywords "word1,word2"] \\
        [--scan-senders "noreply@microsoft,steam"] \\
        [--output-dir output/email_checker] \\
        [--workers 5]

Outlook-family addresses are validated via LZT ``/letters2`` (the LZT
credential + proxy group are required for this).  Gmail addresses are
skipped.  Everything else is verified via IMAPS using a hardcoded
server mapping with ``imap.<domain>`` fallback.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.email_checker.services.dispatcher import classify
from apps.email_checker.services.imap_provider import ImapEmailChecker
from apps.email_checker.services.input_parser import mask_email, parse_file
from apps.email_checker.services.lzt_provider import LztEmailChecker
from apps.email_checker.services.report import write_csv, write_json
from apps.email_checker.services.types import (
    CheckMethod,
    CheckResult,
    CheckStatus,
)
from apps.integrations.models import IntegrationAccount
from apps.integrations.providers.registry import get_or_build_client
from apps.integrations.proxy_pool import build_proxy_pool, get_group_name

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Verify email:password pairs via LZT (Microsoft domains) or IMAPS "
        "(everything else). Gmail is skipped."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--input", required=True,
            help="Path to .txt (email:password per line) or .csv (email,password)",
        )
        parser.add_argument(
            "--lzt-account", required=True,
            help='IntegrationAccount slug (e.g. "lzt-gandalfrivendell")',
        )
        parser.add_argument(
            "--proxy-group", default=None,
            help="Proxy group override (default: auto from account)",
        )
        parser.add_argument(
            "--fetch-emails", type=int, default=0,
            help="If > 0, fetch N latest letters and include them in the report",
        )
        parser.add_argument(
            "--scan-keywords", default="",
            help="Comma-separated keywords; report occurrence count per letter set",
        )
        parser.add_argument(
            "--scan-senders", default="",
            help="Comma-separated sender substrings; report match count",
        )
        parser.add_argument(
            "--output-dir", default="",
            help="Output directory (default: <ROOT_DIR>/output/email_checker)",
        )
        parser.add_argument(
            "--workers", type=int, default=5,
            help="Thread pool size (for IMAP checks only; LZT runs sequentially)",
        )
        parser.add_argument(
            "--lzt-delay", type=float, default=10.0,
            help="Seconds to wait between LZT API calls (rate limit protection)",
        )

    def handle(self, *args, **opts):
        input_path = Path(opts["input"]).expanduser()
        if not input_path.is_file():
            raise CommandError(f"Input file not found: {input_path}")

        pairs = parse_file(input_path)
        if not pairs:
            raise CommandError("No valid email:password entries parsed from input file")
        self.stdout.write(f"Parsed {len(pairs)} entries from {input_path.name}")

        account = self._load_account(opts["lzt_account"])
        credential = account.credential

        proxy_pool = build_proxy_pool()
        proxy_group = opts["proxy_group"] or get_group_name(account)

        facade = get_or_build_client(
            "lzt", credential,
            proxy_pool=proxy_pool,
            proxy_group=proxy_group,
        )
        lzt_checker = LztEmailChecker(facade, proxy_group=proxy_group)

        self.stdout.write(
            f"LZT account: {account.slug} | "
            f"proxy: {proxy_group or 'direct (no proxy)'}"
        )
        imap_checker = ImapEmailChecker(timeout=15.0)

        fetch_limit = max(0, int(opts["fetch_emails"]))
        keywords = [k.strip() for k in opts["scan_keywords"].split(",") if k.strip()]
        senders = [s.strip() for s in opts["scan_senders"].split(",") if s.strip()]

        workers = max(1, int(opts["workers"]))
        lzt_delay = max(0.0, float(opts["lzt_delay"]))

        # Separate LZT (sequential, rate-limited) from IMAP (parallel).
        lzt_pairs = []
        imap_pairs = []
        skip_pairs = []
        for email, password in pairs:
            method = classify(email)
            if method == CheckMethod.LZT:
                lzt_pairs.append((email, password))
            elif method == CheckMethod.SKIP:
                skip_pairs.append((email, password))
            else:
                imap_pairs.append((email, password))

        self.stdout.write(
            f"Dispatch: {len(lzt_pairs)} LZT, {len(imap_pairs)} IMAP, "
            f"{len(skip_pairs)} skip"
        )

        results: list[CheckResult] = []

        # Skipped emails (gmail, malformed)
        for email, _pw in skip_pairs:
            r = CheckResult(
                email=email, status=CheckStatus.SKIPPED,
                method=CheckMethod.SKIP, detail="gmail_or_malformed",
            )
            results.append(r)
            self._log(r)

        # LZT — sequential with delay
        for i, (email, password) in enumerate(lzt_pairs):
            if i > 0 and lzt_delay > 0:
                self.stdout.write(f"  (waiting {lzt_delay:.0f}s for rate limit...)")
                time.sleep(lzt_delay)
            lzt_limit = max(10, fetch_limit) if fetch_limit else 10
            r = lzt_checker.check(
                email, password, fetch_limit=lzt_limit,
                keywords=keywords, senders=senders,
            )
            results.append(r)
            self._log(r)

        # IMAP — parallel
        if imap_pairs:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [
                    pool.submit(
                        imap_checker.check, email, password,
                        fetch_limit=fetch_limit, keywords=keywords, senders=senders,
                    )
                    for email, password in imap_pairs
                ]
                for fut in as_completed(futures):
                    r = fut.result()
                    results.append(r)
                    self._log(r)

        if opts["output_dir"]:
            output_dir = Path(opts["output_dir"])
        else:
            from django.conf import settings
            output_dir = settings.ROOT_DIR / "output" / "email_checker"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_path = output_dir / f"email_check_{ts}.json"
        csv_path = output_dir / f"email_check_{ts}.csv"
        write_json(results, json_path)
        write_csv(results, csv_path)

        self._write_summary(results, json_path, csv_path)

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------

    @staticmethod
    def _load_account(slug: str) -> IntegrationAccount:
        try:
            account = (
                IntegrationAccount.objects
                .select_related("credential")
                .get(slug=slug, is_active=True)
            )
        except IntegrationAccount.DoesNotExist as exc:
            raise CommandError(
                f'Active IntegrationAccount with slug "{slug}" not found.'
            ) from exc

        if account.provider != "lzt":
            raise CommandError(
                f'Account "{slug}" is provider "{account.provider}", expected "lzt"'
            )
        if not hasattr(account, "credential") or not account.credential.is_active:
            raise CommandError(
                f'Account "{slug}" has no active credentials.'
            )
        return account

    def _log(self, r: CheckResult) -> None:
        icon = {
            "valid": "OK  ",
            "invalid": "FAIL",
            "skipped": "SKIP",
            "error": "ERR ",
        }.get(r.status.value, "?   ")
        self.stdout.write(
            f"{icon} [{r.method.value:4s}] {mask_email(r.email):40s} {r.detail}"
        )

    def _write_summary(
        self,
        results: list[CheckResult],
        json_path: Path,
        csv_path: Path,
    ) -> None:
        valid = sum(1 for r in results if r.status == CheckStatus.VALID)
        invalid = sum(1 for r in results if r.status == CheckStatus.INVALID)
        skipped = sum(1 for r in results if r.status == CheckStatus.SKIPPED)
        errors = sum(1 for r in results if r.status == CheckStatus.ERROR)
        self.stdout.write(self.style.SUCCESS(
            f"Done. {valid} valid, {invalid} invalid, "
            f"{skipped} skipped, {errors} errors."
        ))
        self.stdout.write(f"JSON: {json_path}")
        self.stdout.write(f"CSV : {csv_path}")
