"""Replace items_found/items_posted with cycle-level stats + processing_state.

Adds: processing_state, cycle_found, cycle_new, cycle_posted
Removes: items_found, items_posted
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posting', '0025_image_preset_shared_per_game'),
    ]

    operations = [
        # --- Add new columns (all have defaults → safe for prod) ---
        migrations.AddField(
            model_name='dropshiptargeturl',
            name='processing_state',
            field=models.CharField(
                choices=[('idle', 'Idle'), ('fetching', 'Fetching'), ('posting', 'Posting')],
                default='idle',
                help_text='Poster bu URL uzerinde su an ne yapiyor (canli gosterge)',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='dropshiptargeturl',
            name='cycle_found',
            field=models.IntegerField(
                default=0,
                help_text='Son cycle filtrede gorulen toplam (duplicate dahil)',
            ),
        ),
        migrations.AddField(
            model_name='dropshiptargeturl',
            name='cycle_new',
            field=models.IntegerField(
                default=0,
                help_text='Son cycle yeni (duplicate olmayan) item',
            ),
        ),
        migrations.AddField(
            model_name='dropshiptargeturl',
            name='cycle_posted',
            field=models.IntegerField(
                default=0,
                help_text='Son cycle gercekten basilan',
            ),
        ),
        # --- Remove old columns ---
        migrations.RemoveField(
            model_name='dropshiptargeturl',
            name='items_found',
        ),
        migrations.RemoveField(
            model_name='dropshiptargeturl',
            name='items_posted',
        ),
    ]
