from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('buckets', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='bucket',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
