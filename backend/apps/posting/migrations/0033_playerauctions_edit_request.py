from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('posting', '0032_pool_sale_event_item_attribution'),
    ]

    operations = [
        migrations.CreateModel(
            name='PlayerAuctionsEditRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('changes', models.JSONField(default=dict)),
                ('status', models.CharField(choices=[('queued', 'Queued'), ('running', 'Running'), ('succeeded', 'Succeeded'), ('failed', 'Failed')], default='queued', max_length=16)),
                ('error_message', models.TextField(blank=True)),
                ('returned_offer_id', models.CharField(blank=True, max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('active_offer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='playerauctions_edit_requests', to='posting.offerpoolactiveoffer')),
                ('listing', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='playerauctions_edit_requests', to='listings.listing')),
                ('pool_item', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='playerauctions_edit_requests', to='posting.offerpoolitem')),
                ('pool_offer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='playerauctions_edit_requests', to='posting.pooloffer')),
            ],
            options={
                'db_table': 'playerauctions_edit_requests',
            },
        ),
        migrations.AddIndex(
            model_name='playerauctionseditrequest',
            index=models.Index(fields=['status', 'created_at'], name='pa_edit_request_queue_idx'),
        ),
        migrations.AddIndex(
            model_name='playerauctionseditrequest',
            index=models.Index(fields=['listing', 'status'], name='pa_edit_request_listing_idx'),
        ),
    ]
