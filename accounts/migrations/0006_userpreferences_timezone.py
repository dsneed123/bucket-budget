from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_userpreferences_default_bucket_default_transaction_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='userpreferences',
            name='timezone',
            field=models.CharField(default='UTC', max_length=50),
        ),
    ]
