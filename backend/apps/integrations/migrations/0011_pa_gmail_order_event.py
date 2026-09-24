# Generated manually for the signed minimal CodeTracker PA Gmail order bridge.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0010_add_roblox_service_type'),
        ('listings', '0007_listing_marketplace_expires_at'),
        ('orders', '0005_replacement_delivery_faulty_return'),
    ]

    operations = [
        migrations.CreateModel(
            name='PaGmailOrderEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_id', models.UUIDField(unique=True)),
                ('source', models.CharField(max_length=64)),
                ('external_order_id', models.CharField(max_length=128)),
                ('tracking_code', models.CharField(max_length=16)),
                ('market', models.CharField(blank=True, max_length=160)),
                ('automatic_delivery', models.BooleanField(blank=True, null=True)),
                ('observed_at_ms', models.BigIntegerField()),
                ('disposition', models.CharField(choices=[('created', 'Created order report'), ('duplicate', 'Already recorded'), ('unmatched', 'No unique SDA Mart listing matched')], default='unmatched', max_length=20)),
                ('received_at', models.DateTimeField(auto_now_add=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('integration_account', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pa_gmail_order_events', to='integrations.integrationaccount')),
                ('listing', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pa_gmail_order_events', to='listings.listing')),
                ('order', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='pa_gmail_events', to='orders.order')),
            ],
            options={
                'db_table': 'pa_gmail_order_events',
                'ordering': ['-received_at'],
            },
        ),
        migrations.AddIndex(
            model_name='pagmailorderevent',
            index=models.Index(fields=['external_order_id'], name='pa_gmail_event_order_idx'),
        ),
        migrations.AddIndex(
            model_name='pagmailorderevent',
            index=models.Index(fields=['tracking_code'], name='pa_gmail_event_code_idx'),
        ),
        migrations.AddIndex(
            model_name='pagmailorderevent',
            index=models.Index(fields=['disposition', 'received_at'], name='pa_gmail_event_status_idx'),
        ),
    ]
