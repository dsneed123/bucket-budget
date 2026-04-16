from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('buckets', '0002_bucket_archived_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='bucket',
            name='rollover',
            field=models.BooleanField(default=False),
        ),
    ]
