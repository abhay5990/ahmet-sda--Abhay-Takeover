# Generated manually for the replacement delivery and faulty-return audit fields.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0004_orderreplacement'),
        ('posting', '0033_playerauctions_edit_request'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='orderreplacement',
            name='delivery_channel',
            field=models.CharField(default='manual_handoff', max_length=30),
        ),
        migrations.AddField(
            model_name='orderreplacement',
            name='delivery_error',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='orderreplacement',
            name='delivery_message_id',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='orderreplacement',
            name='delivery_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending verified delivery'),
                    ('manual', 'Manual staff handoff required'),
                    ('sent', 'Provider-confirmed customer message sent'),
                    ('failed', 'Customer message failed'),
                ],
                default='manual',
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='FaultyAccountReturn',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reason', models.TextField()),
                ('employee_name', models.CharField(max_length=120)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('pool_item', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='faulty_returns', to='posting.offerpoolitem')),
                ('replacement', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='faulty_returns', to='orders.orderreplacement')),
            ],
            options={'db_table': 'faulty_account_returns', 'ordering': ['-created_at']},
        ),
        migrations.AddConstraint(
            model_name='faultyaccountreturn',
            constraint=models.UniqueConstraint(fields=('replacement',), name='unique_faulty_return_per_replacement'),
        ),
    ]
