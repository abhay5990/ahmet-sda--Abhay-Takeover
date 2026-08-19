from datetime import datetime, timedelta, timezone
import re

from django.db import migrations, models


_PA_FORMATS = (
    '%b-%d-%Y %I:%M:%S %p',
    '%m/%d/%Y %I:%M %p',
    '%m/%d/%Y %I:%M:%S %p',
    '%Y-%m-%dT%H:%M:%S',
)
_TZ_TAG_RE = re.compile(r'\([A-Z]{2,5}\)\s*$')


def _raw_pa_expiry(raw_data):
    raw_data = raw_data or {}
    for source in (
        raw_data,
        raw_data.get('payload') if isinstance(raw_data, dict) else None,
        raw_data.get('details') if isinstance(raw_data, dict) else None,
    ):
        if not isinstance(source, dict):
            continue
        value = source.get('expired_time_string') or source.get('expiredTimeString')
        if value:
            return str(value)
    return ''


def _parse_pa_expiry(value):
    value = _TZ_TAG_RE.sub('', (value or '').strip()).strip()
    for fmt in _PA_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def backfill_playerauctions_expiry(apps, schema_editor):
    Listing = apps.get_model('listings', 'Listing')
    for listing in Listing.objects.filter(
        integration_account__provider='playerauctions',
        marketplace_expires_at__isnull=True,
    ).exclude(listed_at__isnull=True).iterator(chunk_size=500):
        expiry = _parse_pa_expiry(_raw_pa_expiry(listing.raw_data))
        if expiry is None:
            expiry = listing.listed_at + timedelta(days=30)
        Listing.objects.filter(pk=listing.pk).update(marketplace_expires_at=expiry)


class Migration(migrations.Migration):

    dependencies = [
        ('listings', '0006_add_listed_at_removed_at_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='listing',
            name='marketplace_expires_at',
            field=models.DateTimeField(
                blank=True,
                help_text='Provider-reported or provider-duration expiry for this offer.',
                null=True,
            ),
        ),
        migrations.AddIndex(
            model_name='listing',
            index=models.Index(
                fields=['integration_account', 'status', 'marketplace_expires_at'],
                name='listing_acct_stat_exp_idx',
            ),
        ),
        migrations.RunPython(backfill_playerauctions_expiry, migrations.RunPython.noop),
    ]
