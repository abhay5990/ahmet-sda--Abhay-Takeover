import core.encryption
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0003_proxy_model'),
    ]

    operations = [
        migrations.CreateModel(
            name='ServiceCredential',
            fields=[
                ('id',           models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name',         models.CharField(help_text='e.g. "Proxyline Main", "Imgur Production"', max_length=100)),
                ('service_type', models.CharField(choices=[('proxy', 'Proxy Provider'), ('image', 'Image Hosting'), ('storage', 'Cloud Storage'), ('game_service', 'Game Service'), ('other', 'Other')], max_length=50)),
                ('slug',         models.SlugField(unique=True, help_text='e.g. "proxyline-main", "imgur-prod"')),
                ('credentials',  core.encryption.EncryptedJSONField(default=dict, help_text='Service-specific credentials (encrypted at rest)')),
                ('base_url',     models.URLField(blank=True, help_text='Optional: override default API endpoint')),
                ('is_active',    models.BooleanField(default=True)),
                ('notes',        models.TextField(blank=True)),
                ('created_at',   models.DateTimeField(auto_now_add=True)),
                ('updated_at',   models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'service_credentials',
                'ordering': ['service_type', 'name'],
            },
        ),
    ]
