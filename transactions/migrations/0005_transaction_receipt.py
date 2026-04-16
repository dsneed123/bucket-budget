from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transactions', '0004_tag_transaction_tags'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='receipt',
            field=models.ImageField(blank=True, null=True, upload_to='receipts/'),
        ),
    ]
