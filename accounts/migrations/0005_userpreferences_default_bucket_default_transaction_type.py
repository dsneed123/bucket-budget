import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_userpreferences_theme'),
        ('buckets', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='userpreferences',
            name='default_bucket',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='buckets.bucket',
            ),
        ),
        migrations.AddField(
            model_name='userpreferences',
            name='default_transaction_type',
            field=models.CharField(
                blank=True,
                choices=[('expense', 'Expense'), ('income', 'Income')],
                default='expense',
                max_length=10,
            ),
        ),
    ]
