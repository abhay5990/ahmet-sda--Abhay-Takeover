from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("sync", "0003_alter_rawpayload_resource_type_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="rawpayload",
            name="resource_type",
            field=models.CharField(
                choices=[
                    ("orders", "Orders"),
                    ("historical_orders", "Historical Orders"),
                    ("listings", "Listings"),
                    ("owned_products", "Owned Products"),
                    ("reviews", "Reviews"),
                    ("notifications", "Notifications"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="synccheckpoint",
            name="resource_type",
            field=models.CharField(
                choices=[
                    ("orders", "Orders"),
                    ("historical_orders", "Historical Orders"),
                    ("listings", "Listings"),
                    ("owned_products", "Owned Products"),
                    ("reviews", "Reviews"),
                    ("notifications", "Notifications"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="syncrun",
            name="resource_type",
            field=models.CharField(
                choices=[
                    ("orders", "Orders"),
                    ("historical_orders", "Historical Orders"),
                    ("listings", "Listings"),
                    ("owned_products", "Owned Products"),
                    ("reviews", "Reviews"),
                    ("notifications", "Notifications"),
                ],
                max_length=20,
            ),
        ),
    ]
