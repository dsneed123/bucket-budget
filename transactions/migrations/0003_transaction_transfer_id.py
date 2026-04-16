from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0002_transaction_split_group'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='transfer_id',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
    ]
