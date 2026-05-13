# Replace ContentTemplateOverride (JSON spec) with ContentTemplate (plain text placeholders).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0004_fee_rule'),
        ('posting', '0004_content_template_override'),
    ]

    operations = [
        # Remove old model
        migrations.RemoveIndex(
            model_name='contenttemplateoverride',
            name='content_template_lookup_idx',
        ),
        migrations.RemoveConstraint(
            model_name='contenttemplateoverride',
            name='unique_content_template_override',
        ),
        migrations.DeleteModel(
            name='ContentTemplateOverride',
        ),

        # Create new model
        migrations.CreateModel(
            name='ContentTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('marketplace', models.CharField(choices=[('eldorado', 'Eldorado'), ('gameboost', 'GameBoost'), ('g2g', 'G2G'), ('playerauctions', 'PlayerAuctions')], max_length=30)),
                ('template_type', models.CharField(choices=[('title', 'Title'), ('description', 'Description')], max_length=20)),
                ('name', models.CharField(help_text='User-friendly template name, e.g. "Detailed Valorant Title"', max_length=100)),
                ('body', models.TextField(help_text='Template text with {field_name} placeholders')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='content_templates', to='inventory.game')),
            ],
            options={
                'db_table': 'content_templates',
                'ordering': ['game__name', 'marketplace', 'template_type', 'name'],
            },
        ),
        migrations.AddConstraint(
            model_name='contenttemplate',
            constraint=models.UniqueConstraint(fields=('game', 'marketplace', 'name', 'template_type'), name='unique_content_template'),
        ),
        migrations.AddIndex(
            model_name='contenttemplate',
            index=models.Index(fields=['game', 'marketplace', 'template_type'], name='content_template_lookup_idx'),
        ),

        # Add template FKs to PostingDefault
        migrations.AddField(
            model_name='postingdefault',
            name='title_template',
            field=models.ForeignKey(
                blank=True,
                help_text='Selected title template. Null = use legacy title generator.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='posting_defaults_as_title',
                to='posting.contenttemplate',
            ),
        ),
        migrations.AddField(
            model_name='postingdefault',
            name='description_template',
            field=models.ForeignKey(
                blank=True,
                help_text='Selected description template. Null = use legacy description generator.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='posting_defaults_as_description',
                to='posting.contenttemplate',
            ),
        ),
    ]
