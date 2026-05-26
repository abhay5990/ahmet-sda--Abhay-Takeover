"""Drop SubplatformLimit table.

SubplatformLimit has been replaced by GameVariantLimit (added in migration 0010).
Data was already migrated in migration 0010 (migrate_subplatform_limits step).
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('posting', '0011_rename_sub_platform_to_variant'),
    ]

    operations = [
        migrations.DeleteModel(
            name='SubplatformLimit',
        ),
    ]
