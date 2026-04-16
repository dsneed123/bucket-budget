from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('buckets', '0004_bucket_alert_threshold'),
    ]

    operations = [
        migrations.AddField(
            model_name='bucket',
            name='is_uncategorized',
            field=models.BooleanField(default=False),
        ),
    ]
