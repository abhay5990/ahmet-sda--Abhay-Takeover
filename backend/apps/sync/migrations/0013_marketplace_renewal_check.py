from datetime import datetime, timezone as dt_timezone

from django.db import migrations, models
import django.db.models.deletion


def backfill_eldorado_expiry(apps, schema_editor):
    """Seed marketplace_expires_at for Eldorado listings from the last synced
    expireDate so the renewer can order by it. Live reads correct it later."""
    Listing = apps.get_model('listings', 'Listing')
    batch = []
    qs = (Listing.objects
          .filter(integration_account__provider='eldorado', marketplace_expires_at__isnull=True,
                  status__in=['listed', 'paused'])
          .only('id', 'raw_data'))
    for listing in qs.iterator(chunk_size=1000):
        raw = listing.raw_data if isinstance(listing.raw_data, dict) else {}
        value = raw.get('expireDate')
        if not isinstance(value, str) or not value:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt_timezone.utc)
        listing.marketplace_expires_at = parsed
        batch.append(listing)
        if len(batch) >= 1000:
            Listing.objects.bulk_update(batch, ['marketplace_expires_at'])
            batch = []
    if batch:
        Listing.objects.bulk_update(batch, ['marketplace_expires_at'])


class Migration(migrations.Migration):
    dependencies = [
        ('sync', '0012_pa_mart_renewal_attempt'),
        ('listings', '0007_listing_marketplace_expires_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='MarketplaceRenewalCheck',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(max_length=32)),
                ('offer_id', models.CharField(max_length=64)),
                ('outcome', models.CharField(choices=[('renewed', 'Renewed (new expiry verified)'), ('not_due', 'Not due yet (expiry read)'), ('gone', 'Offer no longer exists on the marketplace'), ('not_active', 'Offer is not active on the marketplace'), ('held_sale', 'Held: local sale or order evidence'), ('unproven', 'Saved, but the expiry did not move'), ('failed', 'Read or save failed')], max_length=16)),
                ('previous_expires_at', models.DateTimeField(blank=True, null=True)),
                ('verified_expires_at', models.DateTimeField(blank=True, null=True)),
                ('reason_code', models.CharField(blank=True, max_length=80)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('listing', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='marketplace_renewal_checks', to='listings.listing')),
            ],
            options={
                'db_table': 'marketplace_renewal_checks',
                'indexes': [
                    models.Index(fields=['listing', 'created_at'], name='mrc_listing_created_idx'),
                    models.Index(fields=['provider', 'outcome', 'created_at'], name='mrc_provider_outcome_idx'),
                ],
            },
        ),
        migrations.RunPython(backfill_eldorado_expiry, migrations.RunPython.noop),
    ]
