from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0004_fee_rule'),
    ]

    operations = [
        migrations.AddField(
            model_name='ownedproduct',
            name='ref_key',
            field=models.CharField(
                blank=True, default='', max_length=8,
                help_text='Unique reference key (#ABC1234) for traceability',
            ),
        ),
        migrations.AddIndex(
            model_name='ownedproduct',
            index=models.Index(fields=['ref_key'], name='inventory_o_ref_key_idx'),
        ),
    ]
