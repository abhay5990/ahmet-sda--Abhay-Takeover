"""Make PostingImagePreset shared per game instead of per user.

- Rename ``user`` → ``uploaded_by`` (nullable, audit only)
- Unique constraint: (user, game, sha256) → (game, sha256)
- Index: (user, game, is_active) → (game, is_active)
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


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
        migrations.RunSQL(
            sql="""
                UPDATE posting_image_presets t1
                JOIN (
                    SELECT MIN(id) AS keep_id, game_id, sha256
                    FROM posting_image_presets
                    GROUP BY game_id, sha256
                    HAVING COUNT(*) > 1
                ) t2 ON t1.game_id = t2.game_id
                       AND t1.sha256 = t2.sha256
                       AND t1.id != t2.keep_id
                SET t1.is_active = 0;
            """,
            reverse_sql=migrations.RunSQL.noop,
            # Soft-delete duplicates; the constraint below needs uniqueness
        ),
        migrations.RunSQL(
            sql="""
                DELETE FROM posting_image_presets
                WHERE is_active = 0
                  AND id NOT IN (
                      SELECT keep_id FROM (
                          SELECT MIN(id) AS keep_id FROM posting_image_presets
                          GROUP BY game_id, sha256
                      ) sub
                  );
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
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
