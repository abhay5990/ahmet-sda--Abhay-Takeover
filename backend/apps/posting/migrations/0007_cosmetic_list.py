from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0001_initial'),
        ('posting', '0004_add_exchange_rate'),
        ('posting', '0006_postingdefault_template_constraints'),
    ]

    operations = [
        migrations.CreateModel(
            name='CosmeticList',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(help_text='Display name, e.g. "OG Skins"', max_length=100)),
                ('slug', models.SlugField(help_text='Template field name, e.g. "og_skins" -> {og_skins}')),
                ('items', models.JSONField(default=list, help_text='List of item names to match against')),
                ('match_field', models.CharField(default='cosmetic_titles', help_text='Account field to match against', max_length=50)),
                ('priority', models.PositiveIntegerField(default=0, help_text='Processing order (lower = first)')),
                ('is_active', models.BooleanField(default=True, help_text='Inactive lists are skipped')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cosmetic_lists', to='inventory.game')),
            ],
            options={
                'db_table': 'cosmetic_lists',
                'ordering': ['game', 'priority', 'name'],
                'unique_together': {('game', 'slug')},
            },
        ),
    ]
