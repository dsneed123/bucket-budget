from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='split_group',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
    ]
