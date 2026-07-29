"""Backfill missing credential details (recovery email, email domain, etc.) onto
existing accounts by matching on login.

Accounts pasted into a pool before smart-parsing was added kept only
login/password/email/email_password; the extra columns (recovery email,
recovery email password, email domain) were dropped before reaching the server.
This command re-reads the original tab-separated data from a file, matches each
row to an existing OwnedProduct by login, and fills in the missing detail
fields. It never creates accounts, never changes pool membership, price, or
status — it only updates credential detail columns.

By default it only fills fields that are currently blank (safe backfill). Use
--overwrite to replace existing non-empty values.

Examples:
    # Preview what would change (no writes)
    python manage.py backfill_credential_details --file accounts.tsv --dry-run

    # Backfill blank detail fields on matching accounts
    python manage.py backfill_credential_details --file accounts.tsv

    # Scope matching to one game and overwrite existing values
    python manage.py backfill_credential_details --file accounts.tsv \
        --game fortnite --overwrite
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.inventory.models import OwnedProduct
from apps.posting.services.pool.credential_parser import parse_credential_text

# Detail fields this command backfills (login/password are left untouched:
# login is the match key, and password is an account secret we don't reset here).
_DETAIL_FIELDS = (
    "email",
    "email_password",
    "email_login_link",
    "security_email",
    "security_email_password",
)


class Command(BaseCommand):
    help = (
        "Backfill recovery email / email domain / email details onto existing "
        "accounts by matching tab-separated rows on login."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file", required=True,
            help="Path to a tab-separated file of credential rows (same format "
                 "as the Add-to-pool paste box).",
        )
        parser.add_argument(
            "--delimiter", default="\t",
            help="Column delimiter (default: tab).",
        )
        parser.add_argument(
            "--game", default=None,
            help="Optional game slug to scope matching (recommended to avoid "
                 "cross-game login collisions).",
        )
        parser.add_argument(
            "--overwrite", action="store_true",
            help="Replace existing non-empty detail fields (default: only fill blanks).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Show what would change without saving.",
        )

    def handle(self, *args, **options):
        path = options["file"]
        delimiter = options["delimiter"] or "\t"
        if delimiter == "\\t":
            delimiter = "\t"
        game_slug = options["game"]
        overwrite = options["overwrite"]
        dry_run = options["dry_run"]

        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            raise CommandError(f"Could not read file {path!r}: {exc}") from exc

        rows = parse_credential_text(text, delimiter=delimiter)
        if not rows:
            self.stdout.write(self.style.WARNING("No credential rows found in file."))
            return

        base_qs = OwnedProduct.objects.all()
        if game_slug:
            base_qs = base_qs.filter(game__slug=game_slug)

        matched = updated = not_found = no_change = 0
        missing_logins: list[str] = []

        for cred in rows:
            login = cred["login"].strip().lower()
            if not login:
                continue
            owned_list = list(base_qs.filter(login=login))
            if not owned_list:
                not_found += 1
                missing_logins.append(cred["login"].strip() or "(blank)")
                continue

            for owned in owned_list:
                matched += 1
                changed = self._apply(owned, cred, overwrite)
                if not changed:
                    no_change += 1
                    continue
                if dry_run:
                    self.stdout.write(
                        f"  [dry-run] {owned.login}: would set "
                        f"{', '.join(changed)}"
                    )
                else:
                    owned.save(update_fields=changed + ["updated_at"])
                    self.stdout.write(f"  {owned.login}: updated {', '.join(changed)}")
                updated += 1

        self.stdout.write("")
        summary = (
            f"rows={len(rows)} matched={matched} "
            f"{'would_update' if dry_run else 'updated'}={updated} "
            f"unchanged={no_change} not_found={not_found}"
        )
        self.stdout.write(self.style.SUCCESS(summary))
        if missing_logins:
            preview = ", ".join(missing_logins[:20])
            more = "" if len(missing_logins) <= 20 else f" (+{len(missing_logins) - 20} more)"
            self.stdout.write(self.style.WARNING(
                f"No matching account for: {preview}{more}"
            ))
        if dry_run:
            self.stdout.write(self.style.WARNING("[dry-run] No changes were saved."))

    def _apply(self, owned: OwnedProduct, cred: dict, overwrite: bool) -> list[str]:
        """Set backfillable fields on ``owned``; return the list of changed fields."""
        changed: list[str] = []
        for field in _DETAIL_FIELDS:
            value = cred.get(field, "").strip()
            if not value:
                continue
            current = (getattr(owned, field) or "").strip()
            if current and not overwrite:
                continue
            if current == value:
                continue
            setattr(owned, field, value)
            changed.append(field)
        return changed
