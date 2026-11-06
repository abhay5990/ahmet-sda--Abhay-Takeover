from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('sync', '0012_pa_mart_renewal_attempt'),
        ('listings', '0007_listing_marketplace_expires_at'),
    ]

    # Schema only. Cached-expiry backfill requires separately scoped approval.
    operations = [
        migrations.CreateModel(
            name='MarketplaceRenewalCheck',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('provider', models.CharField(max_length=32)),
                ('offer_id', models.CharField(max_length=64)),
                ('cycle_key', models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ('unresolved_key', models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ('outcome', models.CharField(choices=[('pending', 'Pending (committed before potential write)'), ('unknown', 'Unknown remote outcome (reconciliation hold)'), ('renewed', 'Renewed (new expiry verified)'), ('not_due', 'Not due yet (expiry read)'), ('gone', 'Offer no longer exists on the marketplace'), ('not_active', 'Offer is not active on the marketplace'), ('held_sale', 'Held: local sale or order evidence'), ('unproven', 'Saved, but the expiry did not move'), ('failed', 'Read or save failed')], max_length=16)),
                ('previous_expires_at', models.DateTimeField(blank=True, null=True)),
                ('verified_expires_at', models.DateTimeField(blank=True, null=True)),
                ('reason_code', models.CharField(blank=True, max_length=80)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('listing', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='marketplace_renewal_checks', to='listings.listing')),
                ('integration_account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='marketplace_renewal_checks', to='integrations.integrationaccount')),
            ],
            options={
                'db_table': 'marketplace_renewal_checks',
                'indexes': [
                    models.Index(fields=['listing', 'created_at'], name='mrc_listing_created_idx'),
                    models.Index(fields=['provider', 'outcome', 'created_at'], name='mrc_provider_outcome_idx'),
                    models.Index(fields=['integration_account', 'offer_id', 'outcome'], name='mrc_account_offer_outcome_idx'),
                ],
            },
        ),
    ]
