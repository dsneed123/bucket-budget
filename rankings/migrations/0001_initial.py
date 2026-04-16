import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='NecessitySnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('period_start', models.DateField()),
                ('period_end', models.DateField()),
                ('avg_score', models.DecimalField(blank=True, decimal_places=2, max_digits=4, null=True)),
                ('total_spend', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('want_spend', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('useful_spend', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('need_spend', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('unscored_spend', models.DecimalField(decimal_places=2, default=0, max_digits=12)),
                ('transaction_count', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='necessity_snapshots', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-period_start'],
                'unique_together': {('user', 'period_start', 'period_end')},
            },
        ),
    ]
