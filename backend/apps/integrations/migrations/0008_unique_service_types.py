"""Rename service_type values to unique-per-service identifiers.

Old → New mapping:
    proxy        → proxyline
    image        → imgur  (or imageshack, based on slug)
    storage      → dropbox
    game-service → robuxcrate
    notification → telegram
    email        → firstmail
    google-sheets, other → unchanged
"""

from django.db import migrations, models


# Old value → new value (1:1 services)
_SIMPLE_RENAMES = {
    'proxy': 'proxyline',
    'storage': 'dropbox',
    'game-service': 'robuxcrate',
    'notification': 'telegram',
    'email': 'firstmail',
}

# New choices after migration
_NEW_CHOICES = [
    ('proxyline', 'Proxyline'),
    ('imgur', 'Imgur'),
    ('imageshack', 'ImageShack'),
    ('dropbox', 'Dropbox'),
    ('robuxcrate', 'RobuxCrate'),
    ('telegram', 'Telegram'),
    ('firstmail', 'FirstMail'),
    ('google-sheets', 'Google Sheets'),
    ('other', 'Other'),
]


def forwards(apps, schema_editor):
    ServiceCredential = apps.get_model('integrations', 'ServiceCredential')

    # Simple 1:1 renames
    for old_val, new_val in _SIMPLE_RENAMES.items():
        ServiceCredential.objects.filter(service_type=old_val).update(service_type=new_val)

    # Image → imgur or imageshack (based on slug content)
    for cred in ServiceCredential.objects.filter(service_type='image'):
        if 'imageshack' in (cred.slug or '').lower():
            cred.service_type = 'imageshack'
        else:
            cred.service_type = 'imgur'
        cred.save(update_fields=['service_type'])


def backwards(apps, schema_editor):
    ServiceCredential = apps.get_model('integrations', 'ServiceCredential')

    reverse_map = {v: k for k, v in _SIMPLE_RENAMES.items()}
    for new_val, old_val in reverse_map.items():
        ServiceCredential.objects.filter(service_type=new_val).update(service_type=old_val)

    # imgur/imageshack → image
    ServiceCredential.objects.filter(service_type__in=['imgur', 'imageshack']).update(service_type='image')


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0007_add_google_sheets_service_type'),
    ]

    operations = [
        # 1. Widen choices first (so data migration can write new values)
        migrations.AlterField(
            model_name='servicecredential',
            name='service_type',
            field=models.CharField(choices=_NEW_CHOICES, max_length=50),
        ),
        # 2. Migrate existing data
        migrations.RunPython(forwards, backwards),
    ]
