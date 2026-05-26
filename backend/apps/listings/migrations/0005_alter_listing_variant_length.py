from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('listings', '0004_alter_listing_variant'),
    ]

    operations = [
        migrations.AlterField(
            model_name='listing',
            name='variant',
            field=models.CharField(
                blank=True,
                help_text='Canonical variant slug: pc, psn, xbox, na, euw, etc.',
                max_length=64,
            ),
        ),
    ]
