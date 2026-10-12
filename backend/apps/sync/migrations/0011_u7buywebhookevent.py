# Generated manually for the signed U7Buy seller-event receiver.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0011_pa_gmail_order_event'),
        ('sync', '0010_gameboostwebhookevent'),
    ]

    operations = [
        migrations.CreateModel(
            name='U7BuyWebhookEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_hash', models.CharField(max_length=64, unique=True)),
                ('topic', models.CharField(max_length=120)),
                ('external_order_id', models.CharField(blank=True, max_length=128)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('completed', 'Completed'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('last_error', models.TextField(blank=True)),
                ('received_at', models.DateTimeField(auto_now_add=True)),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('integration_account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='u7buy_webhook_events', to='integrations.integrationaccount')),
            ],
            options={
                'db_table': 'u7buy_webhook_events',
                'ordering': ['received_at'],
            },
        ),
        migrations.AddIndex(
            model_name='u7buywebhookevent',
            index=models.Index(fields=['status', 'received_at'], name='u7buy_webho_status_015122_idx'),
        ),
        migrations.AddIndex(
            model_name='u7buywebhookevent',
            index=models.Index(fields=['integration_account', 'status'], name='u7buy_webho_integra_172255_idx'),
        ),
        migrations.AddIndex(
            model_name='u7buywebhookevent',
            index=models.Index(fields=['external_order_id'], name='u7buy_webho_externa_968fa4_idx'),
        ),
    ]
