"""Management command to run the dropship scheduler as a standalone process.

Usage:
    python manage.py run_dropship_scheduler

Deployment:
    Run as a systemd service (Restart=always) alongside gunicorn.
    See task doc section 8.2 for the service unit file.
"""

from django.core.management.base import BaseCommand

from apps.posting.services.dropship.scheduler import DropshipScheduler


class Command(BaseCommand):
    help = "Run the dropship scheduler (poster + cleaner thread management)"

    def handle(self, *args, **options):
        scheduler = DropshipScheduler()
        scheduler.run()
