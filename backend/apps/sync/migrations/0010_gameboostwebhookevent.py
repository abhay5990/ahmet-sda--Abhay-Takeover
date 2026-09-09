# Generated manually for the signed GameBoost purchase-event receiver.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('integrations', '0002_alter_integrationaccount_provider'),
        ('sync', '0009_add_item_orders_resource_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='GameBoostWebhookEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_id', models.CharField(max_length=255, unique=True)),
                ('topic', models.CharField(max_length=120)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('completed', 'Completed'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('last_error', models.TextField(blank=True)),
                ('received_at', models.DateTimeField(auto_now_add=True)),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('integration_account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='gameboost_webhook_events', to='integrations.integrationaccount')),
            ],
            options={
                'db_table': 'gameboost_webhook_events',
                'ordering': ['received_at'],
            },
        ),
        migrations.AddIndex(
            model_name='gameboostwebhookevent',
            index=models.Index(fields=['status', 'received_at'], name='gameboost_w_status_f90221_idx'),
        ),
        migrations.AddIndex(
            model_name='gameboostwebhookevent',
            index=models.Index(fields=['integration_account', 'status'], name='gameboost_w_integra_eb4e55_idx'),
        ),
    ]
