from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0001_initial'),
        ('buckets', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='MonthlyBudgetAllocation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('year', models.IntegerField()),
                ('month', models.IntegerField()),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('bucket', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='monthly_budget_allocations', to='buckets.bucket')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='monthly_budget_allocations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'unique_together': {('user', 'bucket', 'year', 'month')},
            },
        ),
    ]
