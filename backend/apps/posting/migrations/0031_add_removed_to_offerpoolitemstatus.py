from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posting', '0030_add_seller_uuid_to_target_url'),
    ]

    operations = [
        migrations.AlterField(
            model_name='offerpoolitem',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('reserved', 'Reserved'),
                    ('queued', 'Queued'),
                    ('pushed', 'Pushed'),
                    ('failed', 'Failed'),
                    ('consumed', 'Consumed'),
                    ('removed', 'Removed'),
                ],
                default='pending',
                max_length=10,
            ),
        ),
    ]
