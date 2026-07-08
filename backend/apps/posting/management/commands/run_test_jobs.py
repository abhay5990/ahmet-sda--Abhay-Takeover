"""Management command: trigger test listing jobs for all 9 source accounts."""
import time
from django.core.management.base import BaseCommand
from apps.posting.models import PostingJob, PostingJobItem, PostingJobItemStatus
from apps.integrations.models import IntegrationAccount
from apps.inventory.models import OwnedProduct, Game
from apps.posting.api.stock import _launch_job


ACCOUNTS = [
    {"login": "davidmdodawi5q4v@outlook.com", "game": "minecraft"},
    {"login": "PJYggee",                       "game": "roblox"},
    {"login": "ElectronicPuggg",               "game": "league-of-legends"},
    {"login": "YaBoiRelax",                    "game": "valorant"},
    {"login": "mfucjdku@polosmail.com",        "game": "clash-royale"},
    {"login": "pwblmtbm@fringmail.com",        "game": "clash-of-clans"},
    {"login": "fedorovatn9pz@rambler.ru",      "game": "brawl-stars"},
    {"login": "neasufh980@hotmail.com",        "game": "rainbow-six-siege"},
    {"login": "morozova-7tbga@rambler.ru",     "game": "fortnite"},
]


class Command(BaseCommand):
    help = "Trigger test listing jobs for all 9 source accounts and report results"

    def handle(self, *args, **options):
        stores = list(IntegrationAccount.objects.filter(is_active=True))
        self.stdout.write(f"Active stores ({len(stores)}): {[s.name for s in stores]}")

        job_ids = []

        for acc_info in ACCOUNTS:
            login = acc_info["login"]
            game_slug = acc_info["game"]

            try:
                game = Game.objects.get(slug=game_slug)
            except Game.DoesNotExist:
                self.stdout.write(f"  [{game_slug}] {login}: GAME NOT FOUND — skipping")
                continue

            owned_map = {}
            if game.category_id:
                existing = OwnedProduct.objects.filter(
                    category=game.category,
                    login__in=[login.lower()],
                ).select_related('source_account')
                owned_map = {op.login: op for op in existing}

            total = len(stores)
            try:
                job = PostingJob.objects.create(
                    game=game,
                    source_account=None,
                    settings={},
                    total_count=total,
                )

                items = []
                normalized = login.lower().strip()
                owned = owned_map.get(normalized)
                for store in stores:
                    items.append(PostingJobItem(
                        job=job,
                        login=normalized,
                        owned_product=owned,
                        store=store,
                        marketplace=store.provider,
                    ))
                PostingJobItem.objects.bulk_create(items)
                _launch_job(job, total)
                job_ids.append(job.id)
                self.stdout.write(f"  [{game_slug}] {login}: Job #{job.id} launched ({total} items)")
            except Exception as e:
                self.stdout.write(f"  [{game_slug}] {login}: FAILED: {e}")
                import traceback; traceback.print_exc()

        self.stdout.write(f"\nLaunched {len(job_ids)} jobs: {job_ids}")
        self.stdout.write("Waiting 4 minutes for jobs to complete...")
        time.sleep(240)

        self.stdout.write("\n=== RESULTS ===")
        for job_id in job_ids:
            try:
                job = PostingJob.objects.get(id=job_id)
                items = list(PostingJobItem.objects.filter(job=job).select_related('store'))
                total = len(items)
                success = sum(1 for i in items if i.status == PostingJobItemStatus.SUCCESS)
                failed = sum(1 for i in items if i.status == PostingJobItemStatus.FAILED)
                skipped = sum(1 for i in items if i.status == PostingJobItemStatus.SKIPPED)
                self.stdout.write(f"\nJob #{job_id} [{job.game.slug}] — {job.status}")
                self.stdout.write(f"  Total: {total} | Success: {success} | Failed: {failed} | Skipped: {skipped}")
                for item in items:
                    store_name = item.store.name if hasattr(item.store, 'name') else str(item.store)
                    err = f" — {item.error_message[:100]}" if item.error_message else ""
                    listing_id = f" → listing={item.listing_id}" if getattr(item, 'listing_id', None) else ""
                    self.stdout.write(f"    [{item.status}] {store_name} ({item.marketplace}){listing_id}{err}")
            except Exception as e:
                self.stdout.write(f"Job #{job_id}: Error: {e}")
