from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0001_initial'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='dropshipproduct',
            index=models.Index(fields=['status'], name='ds_product_status_idx'),
        ),
        migrations.AddIndex(
            model_name='dropshipproduct',
            index=models.Index(fields=['-created_at'], name='ds_product_created_idx'),
        ),
        migrations.AddIndex(
            model_name='dropshipproduct',
            index=models.Index(fields=['source_account', 'status'], name='ds_product_account_status_idx'),
        ),
    ]
