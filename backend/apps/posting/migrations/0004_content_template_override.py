# Generated for DB-backed content template overrides.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0004_fee_rule'),
        ('posting', '0003_add_offer_pool_models'),
    ]

    operations = [
        migrations.CreateModel(
            name='ContentTemplateOverride',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category', models.CharField(choices=[('account', 'Account'), ('item', 'Item')], default='account', max_length=20)),
                ('kind', models.CharField(choices=[('stock', 'Stock'), ('dropshipping', 'Dropshipping')], default='stock', max_length=20)),
                ('marketplace', models.CharField(choices=[('default', 'Default'), ('eldorado', 'Eldorado'), ('gameboost', 'GameBoost'), ('g2g', 'G2G'), ('playerauctions', 'PlayerAuctions')], help_text='Use "default" for the base listing content.', max_length=30)),
                ('enabled', models.BooleanField(default=True)),
                ('title_template', models.JSONField(blank=True, help_text='Structured title spec. Leave empty to keep the bundled/default title.', null=True)),
                ('description_template', models.JSONField(blank=True, help_text='Structured description spec. Leave empty to keep the bundled/default description.', null=True)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='content_template_overrides', to='inventory.game')),
            ],
            options={
                'db_table': 'content_template_overrides',
                'ordering': ['game__name', 'kind', 'marketplace'],
            },
        ),
        migrations.AddConstraint(
            model_name='contenttemplateoverride',
            constraint=models.UniqueConstraint(fields=('game', 'category', 'kind', 'marketplace'), name='unique_content_template_override'),
        ),
        migrations.AddIndex(
            model_name='contenttemplateoverride',
            index=models.Index(fields=['game', 'category', 'kind', 'enabled'], name='content_template_lookup_idx'),
        ),
    ]
