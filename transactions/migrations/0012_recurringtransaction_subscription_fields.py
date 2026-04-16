import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0011_recurring_transaction'),
    ]

    operations = [
        migrations.AddField(
            model_name='recurringtransaction',
            name='is_subscription',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='recurringtransaction',
            name='necessity_score',
            field=models.IntegerField(
                blank=True,
                null=True,
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(10),
                ],
            ),
        ),
    ]
