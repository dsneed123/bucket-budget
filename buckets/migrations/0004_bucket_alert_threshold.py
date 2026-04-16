from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('buckets', '0003_bucket_rollover'),
    ]

    operations = [
        migrations.AddField(
            model_name='bucket',
            name='alert_threshold',
            field=models.IntegerField(default=90),
        ),
    ]
