import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('savings', '0005_add_transaction_type_to_contribution'),
    ]

    operations = [
        migrations.AddField(
            model_name='savingsgoal',
            name='is_private',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='savingsgoal',
            name='share_uuid',
            field=models.UUIDField(default=uuid.uuid4, unique=True),
        ),
    ]
