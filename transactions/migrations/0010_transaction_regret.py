from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0009_csvcolumnmapping'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='regret',
            field=models.BooleanField(blank=True, default=None, null=True),
        ),
    ]
