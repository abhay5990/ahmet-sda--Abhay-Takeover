"""Rename PostingDefault.sub_platform → variant."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("posting", "0010_game_variant_system"),
    ]

    operations = [
        migrations.RenameField(
            model_name="PostingDefault",
            old_name="sub_platform",
            new_name="variant",
        ),
    ]
