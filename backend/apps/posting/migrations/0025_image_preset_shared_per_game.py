"""Make PostingImagePreset shared per game instead of per user.

- Rename ``user`` → ``uploaded_by`` (nullable, audit only)
- Unique constraint: (user, game, sha256) → (game, sha256)
- Index: (user, game, is_active) → (game, is_active)
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def dedupe_presets_forward(apps, schema_editor):
    """Keep one active preset per (game, sha256); soft-delete then hard-delete extras.

    Portable across MySQL and SQLite (avoids MySQL-only UPDATE ... JOIN).
    """
    PostingImagePreset = apps.get_model("posting", "PostingImagePreset")

    seen = set()
    deactivate_ids = []
    for row in (
        PostingImagePreset.objects.order_by("id")
        .values_list("id", "game_id", "sha256")
        .iterator()
    ):
        pk, game_id, sha256 = row
        key = (game_id, sha256)
        if key in seen:
            deactivate_ids.append(pk)
        else:
            seen.add(key)

    if deactivate_ids:
        PostingImagePreset.objects.filter(id__in=deactivate_ids).update(is_active=False)

    # Remove inactive duplicates that are not the kept (min id) row per hash.
    keep_ids = set()
    seen.clear()
    for row in (
        PostingImagePreset.objects.order_by("id")
        .values_list("id", "game_id", "sha256")
        .iterator()
    ):
        pk, game_id, sha256 = row
        key = (game_id, sha256)
        if key not in seen:
            seen.add(key)
            keep_ids.add(pk)

    PostingImagePreset.objects.filter(is_active=False).exclude(id__in=keep_ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("posting", "0024_fix_genshin_region_source_keys"),
    ]

    operations = [
        # 1. Remove old constraint and index
        migrations.RemoveConstraint(
            model_name="postingimagepreset",
            name="unique_posting_image_preset_hash",
        ),
        migrations.RemoveIndex(
            model_name="postingimagepreset",
            name="posting_img_user_game_idx",
        ),
        # 2. Rename user → uploaded_by
        migrations.RenameField(
            model_name="postingimagepreset",
            old_name="user",
            new_name="uploaded_by",
        ),
        # 3. Make uploaded_by nullable with SET_NULL
        migrations.AlterField(
            model_name="postingimagepreset",
            name="uploaded_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="posting_image_presets",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # 4. Deduplicate: keep one active preset per (game, sha256)
        # before adding the new unique constraint.
        migrations.RunPython(dedupe_presets_forward, migrations.RunPython.noop),
        # 5. Add new constraint and index
        migrations.AddConstraint(
            model_name="postingimagepreset",
            constraint=models.UniqueConstraint(
                fields=["game", "sha256"],
                name="unique_posting_image_preset_game_hash",
            ),
        ),
        migrations.AddIndex(
            model_name="postingimagepreset",
            index=models.Index(
                fields=["game", "is_active"],
                name="posting_img_game_active_idx",
            ),
        ),
    ]
