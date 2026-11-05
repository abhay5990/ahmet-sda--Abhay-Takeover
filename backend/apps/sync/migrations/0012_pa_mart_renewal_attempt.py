from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('sync', '0011_u7buywebhookevent'),
        ('listings', '0007_listing_marketplace_expires_at'),
        ('integrations', '0012_add_u7buy_provider'),
    ]

    operations = [
        migrations.CreateModel(
            name='PaMartRenewalAttempt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('request_id', models.CharField(max_length=128, unique=True)),
                ('old_offer_id', models.CharField(max_length=16)),
                ('new_offer_id', models.CharField(blank=True, max_length=16)),
                ('previous_expires_at', models.DateTimeField()),
                ('verified_expires_at', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('succeeded', 'Succeeded'), ('rejected', 'Rejected before write'), ('unknown', 'Unknown remote outcome')], default='pending', max_length=16)),
                ('reason_code', models.CharField(blank=True, max_length=80)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('listing', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='pa_mart_renewal_attempts', to='listings.listing')),
                ('integration_account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='pa_mart_renewal_attempts', to='integrations.integrationaccount')),
            ],
            options={
                'db_table': 'pa_mart_renewal_attempts',
                'constraints': [models.UniqueConstraint(fields=('listing', 'old_offer_id', 'previous_expires_at'), name='unique_pa_mart_renewal_cycle')],
                'indexes': [
                    models.Index(fields=['integration_account', 'old_offer_id'], name='pa_renew_account_old_idx'),
                    models.Index(fields=['integration_account', 'new_offer_id'], name='pa_renew_account_new_idx'),
                    models.Index(fields=['listing', 'status'], name='pa_renew_listing_status_idx'),
                ],
            },
        ),
    ]
