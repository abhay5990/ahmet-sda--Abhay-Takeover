# Add limit_choices_to on PostingDefault template FK fields.
# No schema change — only Django-level form/admin validation.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posting', '0005_content_template_v2'),
    ]

    operations = [
        migrations.AlterField(
            model_name='postingdefault',
            name='title_template',
            field=models.ForeignKey(
                blank=True,
                help_text='Selected title template. Null = use legacy title generator.',
                limit_choices_to={'template_type': 'title'},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='posting_defaults_as_title',
                to='posting.contenttemplate',
            ),
        ),
        migrations.AlterField(
            model_name='postingdefault',
            name='description_template',
            field=models.ForeignKey(
                blank=True,
                help_text='Selected description template. Null = use legacy description generator.',
                limit_choices_to={'template_type': 'description'},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='posting_defaults_as_description',
                to='posting.contenttemplate',
            ),
        ),
    ]
