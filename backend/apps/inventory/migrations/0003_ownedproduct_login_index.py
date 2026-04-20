from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0002_dropship_product_indexes'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='ownedproduct',
            index=models.Index(fields=['login'], name='owned_produ_login_idx'),
        ),
    ]
