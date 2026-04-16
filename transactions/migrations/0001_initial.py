from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('banking', '0001_initial'),
        ('buckets', '0005_bucket_is_uncategorized'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Transaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('transaction_type', models.CharField(choices=[('expense', 'Expense'), ('income', 'Income'), ('transfer', 'Transfer')], max_length=10)),
                ('description', models.CharField(max_length=255)),
                ('vendor', models.CharField(blank=True, max_length=100)),
                ('date', models.DateField()),
                ('necessity_score', models.IntegerField(blank=True, null=True, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(10)])),
                ('notes', models.TextField(blank=True)),
                ('is_recurring', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='transactions', to=settings.AUTH_USER_MODEL)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='transactions', to='banking.bankaccount')),
                ('bucket', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='transactions', to='buckets.bucket')),
            ],
            options={
                'ordering': ['-date', '-created_at'],
            },
        ),
    ]
