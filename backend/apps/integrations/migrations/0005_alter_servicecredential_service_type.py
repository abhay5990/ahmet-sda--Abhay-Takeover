from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0004_service_credential'),
    ]

    operations = [
        migrations.RunSQL(
            sql="UPDATE service_credentials SET service_type = 'game-service' WHERE service_type = 'game_service'",
            reverse_sql="UPDATE service_credentials SET service_type = 'game_service' WHERE service_type = 'game-service'",
        ),
        migrations.AlterField(
            model_name='servicecredential',
            name='service_type',
            field=models.CharField(
                choices=[
                    ('proxy',        'Proxy Provider'),
                    ('image',        'Image Hosting'),
                    ('storage',      'Cloud Storage'),
                    ('game-service', 'Game Service'),
                    ('other',        'Other'),
                ],
                max_length=50,
            ),
        ),
    ]
