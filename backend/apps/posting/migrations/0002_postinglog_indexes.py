from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posting', '0001_initial'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='postinglog',
            index=models.Index(fields=['task_name', '-created_at'], name='posting_log_task_created_idx'),
        ),
        migrations.AddIndex(
            model_name='postinglog',
            index=models.Index(fields=['level'], name='posting_log_level_idx'),
        ),
    ]
