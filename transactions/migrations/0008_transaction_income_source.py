from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0007_incomesource'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='income_source',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='transactions',
                to='transactions.incomesource',
            ),
        ),
    ]
